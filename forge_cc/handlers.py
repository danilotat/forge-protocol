"""Hook policy for the Forge Protocol.

The Hermes port exposed nine tools the orchestrator could *choose* to call.
Claude Code lets the harness run this logic unconditionally, which is the
whole point of the port: enforcement stops depending on the model's goodwill.

Mapping from the old plugin tools to hook events:

    forge_log             -> UserPromptSubmit (message counting) + SessionEnd
    forge_get_state       -> SessionStart (context injection) + `forge state`
    forge_validate_input  -> UserPromptSubmit
    forge_validate_output -> Stop / SubagentStop
    forge_checkpoint      -> UserPromptSubmit
    forge_set_mode        -> `forge set-mode` (driven by the /*-mode skills)
    (new)                 -> PreToolUse write-lock

Every handler is a plain function from payload dict to output dict, so the
tests drive them directly without spawning Claude Code.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import hookio
from .paths import (
    PLUGIN_ROOT,
    cli_path,
    ensure_importable,
    get_current_session,
    audit_blocks,
    audit_inflight_since,
    bump_audit_blocks,
    consume_pending_audit,
    modes_dir,
    reset_audit_blocks,
    set_audit_inflight,
    set_current_session,
    set_pending_audit,
    set_mode_request,
    souls_dir,
)

ensure_importable()

from lib import auditor  # noqa: E402
from lib.audit import check_audit_reminders  # noqa: E402
from lib.checkpoints import check_checkpoint, get_session_end_prompt  # noqa: E402
from lib.modes import Mode, load_all_modes  # noqa: E402
from lib.state import Session, StateManager  # noqa: E402
from lib.validator import get_input_rules, get_output_rules  # noqa: E402

#: Tools that write to the user's files. Forbidden in every thinking mode —
#: "never rewrites" and "never fills gaps" are rules the harness can enforce
#: outright rather than merely request.
WRITE_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})

#: Shell programs whose whole job is writing a file. Denying Bash outright in a
#: thinking mode is not an option — the slash-command skills reach the `forge`
#: CLI through it — so the write-lock inspects the command instead.
_SHELL_WRITERS = frozenset({
    "tee", "dd", "truncate", "install", "cp", "mv", "ln", "patch", "rsync",
})

#: Interpreters given inline code. We cannot know what the snippet does, and
#: in a thinking mode "run some code I wrote for you" is the violation itself.
_INLINE_CODE = {
    "python": ("-c",), "python3": ("-c",), "node": ("-e", "--eval"),
    "perl": ("-e",), "ruby": ("-e",), "php": ("-r",), "bash": ("-c",), "sh": ("-c",),
}

#: Redirection targets that write nothing the user cares about. The skills
#: themselves use `>/dev/null`.
_SINK_TARGETS = frozenset({"/dev/null", "/dev/stdout", "/dev/stderr", "/dev/tty"})

#: Modes that apply cognitive friction. Executor is deliberately excluded:
#: it is the no-friction mode, and giving it zero overhead is a feature.
THINKING_MODES = frozenset({"forge", "anvil", "crucible"})

_FALSEY = ("0", "false", "no", "off")


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() not in _FALSEY


def _max_revisions() -> int:
    """How many times one turn may be sent back by the auditor.

    One revision is the honest default: the point is to catch a violation and
    give the model a chance to fix it, not to grind the user through four
    drafts of the same answer at ~7s of audit each.
    """
    raw = os.environ.get("FORGE_MAX_REVISIONS")
    if not raw:
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def _suppressed() -> bool:
    """True inside the auditor's own `claude -p` child process.

    `--safe-mode` already stops the child from loading this plugin; this is
    the second lock on the same door.
    """
    return bool(os.environ.get(auditor.CHILD_ENV_VAR))


# ---------------------------------------------------------------------------
# Shared lookups
# ---------------------------------------------------------------------------

def load_modes() -> dict[str, Mode]:
    directory = modes_dir()
    if not directory.is_dir():
        return {}
    try:
        return load_all_modes(directory)
    except (OSError, ValueError, RuntimeError):
        return {}


def resolve_session_id(payload: dict[str, Any]) -> str:
    return (
        payload.get("session_id")
        or get_current_session(payload.get("cwd"))
        or "default"
    )


def _session_and_mode(payload: dict[str, Any]) -> tuple[StateManager, Session, Mode | None]:
    sm = StateManager()
    session = sm.get_or_create_session(resolve_session_id(payload))
    mode = load_modes().get(session.current_mode)
    return sm, session, mode


def _messages_in_current_mode(session: Session) -> int:
    """How many messages have been sent since entering the current mode."""
    if not session.mode_history:
        return session.message_count
    prior = sum(e.message_count for e in session.mode_history[:-1])
    return max(0, session.message_count - prior)


def _rule_lines(items: list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


#: A mode command in the raw prompt, in any of the forms Claude Code uses:
#: `/forge-mode` when the plugin is loaded bare, and
#: `/forge-protocol:forge-mode` — plus a `<command-name>` wrapper — once it is
#: installed under its plugin namespace. Requiring a leading `/` or `:` keeps
#: prose ("the executor-mode skill is nice") from counting as consent.
_MODE_COMMAND_RE = re.compile(r"[/:]\s*(?:[a-z0-9._-]+:)?(forge|anvil|crucible|executor)-mode\b")


def requested_mode(prompt: str) -> str | None:
    """Which mode, if any, the user's own prompt asked for.

    Matched against the raw prompt the user submitted — which is the whole
    point: it distinguishes "the user typed /executor-mode" from "the model
    decided to invoke the executor-mode skill so it could write a file".
    """
    if not prompt:
        return None
    match = _MODE_COMMAND_RE.search(prompt.lower())
    return match.group(1) if match else None


_SET_MODE_RE = re.compile(r"\bforge\b[^\n|;&]*\bset-mode\b")


def _switches_mode(command: str) -> bool:
    """True if a shell command tries to change the active mode.

    Mode changes are applied by `UserPromptSubmit` from the user's own prompt,
    so nothing legitimate needs this any more — and leaving it reachable meant
    `Bash(forge set-mode executor --force)` then `Write` walked through the
    write-lock in three tool calls.
    """
    return bool(_SET_MODE_RE.search(command or ""))


def bash_write_intent(command: str) -> str | None:
    """Describe how a shell command writes a file, or None if it doesn't.

    Best-effort and deliberately narrow: it catches the forms a model actually
    reaches for when the file tools are denied — a redirect, `tee`, an in-place
    edit — without trying to be a shell. It is the second of three layers, not
    a sandbox: `Write`/`Edit` denial above it is airtight, and the independent
    output audit below it is what catches "I did the work for you" however the
    work got done. A determined bypass (`python3 -c 'open(...)'`) still gets
    through here and is caught there.
    """
    if not command or not command.strip():
        return None

    try:
        import shlex

        tokens = shlex.split(command, comments=True)
    except ValueError:
        # Unbalanced quotes — fall back to the raw string.
        tokens = command.split()

    for index, token in enumerate(tokens):
        # Output redirection in its many spellings: `>`, `>>`, `1>`, `2>`,
        # `&>`, `>|` (zsh clobber). `2>&1` and `>&2` are fd dups, not writes.
        if token in (">", ">>", "1>", "1>>", "2>", "2>>", "&>", "&>>", ">|"):
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            if target and target not in _SINK_TARGETS:
                return f"shell redirection to {target}"
            continue
        if len(token) > 1 and token[0] in ">&" and ">" in token and not token.startswith(">&"):
            target = token.lstrip(">&|")
            if target and target not in _SINK_TARGETS:
                return f"shell redirection to {target}"
            continue

        base = token.rsplit("/", 1)[-1]
        if base in _SHELL_WRITERS:
            return f"`{base}` writes a file"
        # In-place edit: sed -i / --in-place, perl -i/-pi, ruby -i
        if base in ("sed", "perl", "ruby", "gawk", "awk"):
            rest = tokens[index + 1 : index + 4]
            if any(
                a == "-i" or a.startswith("-i") or a.startswith("-pi")
                or a.startswith("--in-place")
                for a in rest
            ):
                return f"`{base}` edits a file in place"

        # Inline code: unbounded, so treated as intent to write.
        flags = _INLINE_CODE.get(base)
        if flags and any(a in flags for a in tokens[index + 1 : index + 5]):
            return f"`{base}` running inline code"

        # `git checkout -- path` / `git restore` overwrite the working tree.
        if base == "git" and any(
            a in ("checkout", "restore", "apply", "stash") for a in tokens[index + 1 : index + 3]
        ):
            return "`git` rewriting the working tree"

    return None


def _spawn_audit(mode_id: str, response: str, user_message: str, cwd: str | None) -> None:
    """Start the audit in a detached process and return immediately.

    start_new_session detaches it from the hook's process group, so it
    survives the hook exiting. Failures are swallowed: an audit that never
    runs must look exactly like no audit at all.
    """
    import subprocess
    import sys

    payload = json.dumps({
        "mode": mode_id,
        "response": response,
        "user_message": user_message,
        "cwd": cwd or os.getcwd(),
    })
    try:
        set_audit_inflight(cwd)
        proc = subprocess.Popen(
            [sys.executable, "-m", "forge_cc.audit_worker"],
            cwd=str(PLUGIN_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        proc.stdin.write(payload.encode("utf-8"))
        proc.stdin.close()
    except Exception:  # noqa: BLE001
        from .paths import clear_audit_inflight

        clear_audit_inflight(cwd)


def _read_soul(name: str) -> str:
    """Read a soul file by name, tolerating its absence."""
    path = souls_dir() / name
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _violation_lines(audit: "auditor.AuditResult") -> str:
    lines = []
    for v in audit.violations:
        detail = f"  - [{v.kind}] {v.rule}"
        if v.reason:
            detail += f"\n    why: {v.reason}"
        if v.quote:
            detail += f'\n    quote: "{v.quote}"'
        lines.append(detail)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# SessionStart
# ---------------------------------------------------------------------------

def session_start(payload: dict[str, Any]) -> dict[str, Any]:
    """Announce the active mode, inject its soul, and surface audit reminders."""
    if _suppressed():
        return {}

    session_id = payload.get("session_id") or "default"
    cwd = payload.get("cwd")
    set_current_session(session_id, cwd)

    sm = StateManager()
    session = sm.get_or_create_session(session_id)
    modes = load_modes()
    mode = modes.get(session.current_mode)

    lines = [
        "# Forge Protocol active",
        "",
        f"Active mode: **{mode.name if mode else session.current_mode}** "
        f"(`{session.current_mode}`)",
        f"Messages this session: {session.message_count}",
        f"FORGE_CLI: {cli_path()}",
        "",
        "Switch modes with `/forge-mode`, `/anvil-mode`, `/crucible-mode`, "
        "`/executor-mode`. `/forge-status` shows state; `/forge-audit` runs a "
        "self-audit.",
    ]

    if session.current_mode in THINKING_MODES:
        lines += [
            "",
            "Enforcement in this mode is not advisory: a PreToolUse hook denies "
            f"{', '.join(sorted(WRITE_TOOLS))}, and an independent auditor reviews "
            "your response when you finish. Do not attempt to write files.",
        ]

    # The orchestrator soul carries the thinking-vs-execution classifier and
    # the mismatch notice. Executor is the default mode, so without this the
    # protocol would never nudge a user who parks there — it is injected in
    # every mode, once per session, which costs nothing per turn.
    orchestrator = _read_soul("forge-orchestrator.md")
    if orchestrator:
        lines += ["", "---", "", orchestrator]

    if mode:
        try:
            soul = mode.load_system_prompt(PLUGIN_ROOT).strip()
        except (OSError, ValueError):
            soul = ""
        if soul:
            lines += ["", "---", "", soul]

    reminders = check_audit_reminders(session)
    if reminders:
        lines += ["", "## Audit reminders", ""]
        lines += [f"- {r.message}" for r in reminders]

    return hookio.additional_context("SessionStart", "\n".join(lines))


# ---------------------------------------------------------------------------
# UserPromptSubmit
# ---------------------------------------------------------------------------

def user_prompt_submit(payload: dict[str, Any]) -> dict[str, Any]:
    """Count the turn, check the mode's entry rules, deliver checkpoints."""
    if _suppressed():
        return {}

    sm, session, mode = _session_and_mode(payload)

    # Apply mode changes the USER asked for, here, before anything else acts
    # on the turn. Two reasons this belongs in the hook rather than in the
    # skill: the switch becomes deterministic (the model cannot forget it or
    # get it wrong), and the skill stops needing a Bash round-trip whose JSON
    # output was rendered in full to the user.
    requested = requested_mode(payload.get("prompt") or "")
    switched_to = ""
    if requested:
        # Still recorded, so a `forge set-mode` from any other caller sees the
        # user's consent — see forge_cc.paths.set_mode_request.
        set_mode_request(requested, payload.get("cwd"))

        if requested != session.current_mode:
            modes = load_modes()
            current = modes.get(session.current_mode)
            allowed = not (
                current
                and current.transitions.allowed_to
                and requested not in current.transitions.allowed_to
            )
            if allowed and requested in modes:
                session = sm.switch_mode(session.session_id, requested)
                mode = modes[requested]
                switched_to = requested

    # A new user turn gets a fresh revision budget for the output audit.
    reset_audit_blocks(payload.get("cwd"))

    # Replaces forge_log: one write, no round-trip through the helpers.
    session.message_count += 1
    session.updated_at = time.time()
    sm._write_session(session)

    outputs: list[dict[str, Any]] = []

    if switched_to:
        target = load_modes().get(switched_to)
        locked = switched_to in THINKING_MODES
        outputs.append(
            hookio.additional_context(
                "UserPromptSubmit",
                f"Forge Protocol — the user switched to **{target.name if target else switched_to}** "
                f"(`{switched_to}`). The switch is already applied; do not run "
                "`forge set-mode`."
                + (
                    f"\n\nWrite tools ({', '.join(sorted(WRITE_TOOLS))}) are now denied, "
                    "and an independent auditor reviews your responses."
                    if locked
                    else "\n\nNo friction applies in this mode."
                ),
            )
        )

    # Deliver any background finding BEFORE the mode gate. The finding is
    # about a response the previous (thinking) mode produced, so switching to
    # Executor must not swallow it.
    pending = _await_pending_audit(payload.get("cwd"))
    if pending:
        outputs.append(
            hookio.additional_context(
                "UserPromptSubmit",
                "Forge Protocol — the independent auditor flagged your PREVIOUS "
                "response. Do not repeat these violations in this turn, and do "
                "not apologise for them or re-answer the earlier question:\n\n"
                f"{pending}",
            )
        )

    if mode is None or session.current_mode not in THINKING_MODES:
        return hookio.merge(*outputs)

    audit = _audit_input_if_due(payload, session, mode)
    if audit is not None and not audit.compliant and audit.violations:
        sm.log_violation(
            session.session_id,
            session.current_mode,
            "input",
            audit.violations[0].rule[:80],
            audit.violations[0].reason,
        )
        reason = (
            f"Forge Protocol — {mode.name} entry requirements are not met.\n\n"
            f"{_violation_lines(audit)}\n\n"
            "Tell the user what is missing and ask for it. Do not do the "
            "thinking work for them."
        )
        if _flag("FORGE_INPUT_BLOCK", False):
            return hookio.block(reason)
        outputs.append(hookio.additional_context("UserPromptSubmit", reason))
    elif audit is None and mode.input_rules:
        # Auditor unavailable: hand the rules over for self-evaluation, which
        # is the original Hermes behavior.
        outputs.append(
            hookio.additional_context(
                "UserPromptSubmit",
                f"Forge Protocol — {mode.name} entry requirements:\n"
                f"{_rule_lines(mode.input_rules)}\n"
                "Evaluate the user's message against these before engaging. "
                "If a rule is unmet, say what is missing instead of proceeding.",
            )
        )

    checkpoint = check_checkpoint(session, mode)
    if checkpoint.due:
        session.last_checkpoint_at = session.message_count
        session.updated_at = time.time()
        sm._write_session(session)
        outputs.append(
            hookio.additional_context(
                "UserPromptSubmit",
                "Forge Protocol — metacognitive checkpoint is due. Deliver this "
                "to the user verbatim, then wait for their answer before "
                f"continuing:\n\n> {checkpoint.prompt}",
            )
        )

    return hookio.merge(*outputs)


def _await_pending_audit(cwd: str | None) -> str | None:
    """Collect a background finding, waiting briefly if one is still running.

    Users normally spend longer typing than the audit takes, so this usually
    returns immediately. The wait is capped so a slow or dead worker can never
    stall a turn; a finding that misses its window simply arrives on the next.
    """
    import time as _time

    pending = consume_pending_audit(cwd)
    if pending:
        return pending

    started = audit_inflight_since(cwd)
    if started is None:
        return None

    try:
        budget = float(os.environ.get("FORGE_AUDIT_WAIT") or 2.0)
    except ValueError:
        budget = 2.0

    deadline = _time.monotonic() + max(0.0, budget)
    while _time.monotonic() < deadline:
        _time.sleep(0.05)
        pending = consume_pending_audit(cwd)
        if pending:
            return pending
        if audit_inflight_since(cwd) is None:
            return None  # worker finished and found nothing
    return None


def _audit_input_if_due(
    payload: dict[str, Any],
    session: Session,
    mode: Mode,
) -> "auditor.AuditResult | None":
    """Audit the prompt against the mode's entry rules, when that is worth 6s.

    Input rules are *entry* requirements — "the user must submit their own
    draft", "at least 3 distinct ideas before the LLM engages". Auditing them
    on every turn would put a blocking model call in front of every prompt for
    no extra safety, so by default this runs on the first turn after entering
    the mode. FORGE_INPUT_AUDIT_ALWAYS=1 restores per-turn auditing.
    """
    if not mode.input_rules:
        return None
    if not auditor.is_available():
        return None
    if not _flag("FORGE_INPUT_AUDIT_ALWAYS", False):
        if _messages_in_current_mode(session) > 1:
            return None

    prompt = payload.get("prompt") or ""
    if not prompt.strip():
        return None

    # This used to force haiku "because the check is cheap". Measured on this
    # workload haiku is *slower* than sonnet — it needs an extra round-trip to
    # satisfy the JSON schema — so the override is gone. FORGE_INPUT_AUDITOR_MODEL
    # still overrides if someone wants a different model here.
    override = os.environ.get("FORGE_INPUT_AUDITOR_MODEL")
    previous = os.environ.get("FORGE_AUDITOR_MODEL")
    if override:
        os.environ["FORGE_AUDITOR_MODEL"] = override
    try:
        return auditor.audit_input(prompt, get_input_rules(mode))
    finally:
        if override:
            if previous is None:
                os.environ.pop("FORGE_AUDITOR_MODEL", None)
            else:
                os.environ["FORGE_AUDITOR_MODEL"] = previous


# ---------------------------------------------------------------------------
# PreToolUse
# ---------------------------------------------------------------------------

def pre_tool_use(payload: dict[str, Any]) -> dict[str, Any]:
    """Deny write-capable tools while a thinking mode is active.

    This is the one guarantee the Hermes port could not make. Forge's "never
    write content the user should write", Anvil's "never produce a revised
    version", and Crucible's "never fill in the negative space" stop being
    instructions the model may rationalize around.

    Deliberately NOT guarded by `_suppressed()`. That guard exists to stop the
    auditor's own child process re-entering the hooks that call the auditor;
    this hook never calls it, so honouring FORGE_AUDITOR_CHILD here would let
    a single stray environment variable switch the write-lock off.
    """
    tool_name = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input")
    tool_input = tool_input if isinstance(tool_input, dict) else {}

    what = ""
    if tool_name in WRITE_TOOLS:
        what = tool_name
    elif tool_name == "Bash":
        command = str(tool_input.get("command", ""))
        if _switches_mode(command):
            what = "Bash (changing the active mode)"
        else:
            intent = bash_write_intent(command)
            if intent:
                what = f"Bash ({intent})"

    if not what:
        return {}

    sm, session, mode = _session_and_mode(payload)
    if session.current_mode not in THINKING_MODES:
        return {}

    # Fail CLOSED when the mode definition will not load. The user chose a
    # thinking mode; a broken or missing modes/ directory must not be a way to
    # unlock writes.
    mode_name = mode.name if mode else session.current_mode
    forbidden = mode.behaviors.forbidden if mode else []
    rationale = (
        _rule_lines(forbidden[:3]) if forbidden
        else "  - (mode rules unavailable — refusing rather than guessing)"
    )

    sm.log_violation(
        session.session_id,
        session.current_mode,
        "output",
        f"tool:{tool_name}",
        f"{what} denied in {session.current_mode} mode",
    )

    return hookio.deny_tool(
        f"Forge Protocol: {what} is blocked in {mode_name}. This mode "
        "forbids producing the work for the user:\n"
        f"{rationale}\n"
        "Writing the file through a shell redirect instead of the Write tool is "
        "the same violation. Describe what needs to change and let the user "
        "write it, or switch to `/executor-mode` if this is genuinely a "
        "mechanical task."
    )


# ---------------------------------------------------------------------------
# Stop / SubagentStop
# ---------------------------------------------------------------------------

def stop(payload: dict[str, Any]) -> dict[str, Any]:
    """Audit the finished response against the mode's behavioral rules."""
    if _suppressed():
        return {}

    # A blocking Stop hook re-enters the agent, so blocking needs a ceiling.
    # `stop_hook_active` is necessary but NOT sufficient: measured against
    # Claude Code 2.1.258, a second block within the same turn still arrives
    # with the flag false, so relying on it alone lets the audit demand
    # revision after revision. We keep our own budget per user turn.
    if payload.get("stop_hook_active"):
        return {}

    # The budget bounds re-entry, so it only applies to the blocking path —
    # and it is checked before the audit, not after, so an exhausted turn does
    # not spend ~9s judging a response it cannot act on. Notifications never
    # re-enter the agent and are never capped.
    blocking = _flag("FORGE_OUTPUT_BLOCK", False)
    if blocking and audit_blocks(payload.get("cwd")) >= _max_revisions():
        return {}

    sm, session, mode = _session_and_mode(payload)
    if mode is None or session.current_mode not in THINKING_MODES:
        return {}

    from .transcript import last_user_text, response_under_audit

    transcript_path = payload.get("transcript_path")
    # Anchored on the user's turn, not "newest assistant message": the hook
    # races the transcript write, and auditing the previous turn's response
    # blocks a reply nobody judged.
    response = response_under_audit(transcript_path)
    if not response:
        return {}

    if not blocking and _flag("FORGE_AUDITOR_ASYNC", True) and auditor.is_available():
        # The verdict is not needed until the next turn, so do not make the
        # user wait ~4s for it. Detach and return now.
        _spawn_audit(mode.id, response, last_user_text(transcript_path), payload.get("cwd"))
        return {}

    audit = auditor.audit_output(
        response,
        get_output_rules(mode),
        user_message=last_user_text(transcript_path),
    )
    if audit is None:
        return {}  # disabled: the soul already asks for a self-check
    if audit.error:
        # Never let an auditor failure interfere with the user's session.
        return {}
    if audit.compliant or not audit.violations:
        return {}

    for v in audit.violations:
        sm.log_violation(
            session.session_id,
            session.current_mode,
            "output",
            v.rule[:80],
            v.reason,
        )

    reason = (
        f"Forge Protocol — an independent auditor ({audit.auditor_model}) found "
        f"your response violates {mode.name}:\n\n"
        f"{_violation_lines(audit)}\n\n"
        "Revise to address every violation. Do not argue with the audit; it did "
        "not see your reasoning, only your output, which is the point."
    )

    if not blocking:
        # Carry the detail into the next turn: the user has already read the
        # response, so an in-place rewrite buys nothing but a second copy.
        set_pending_audit(reason, payload.get("cwd"))
        count = len(audit.violations)
        return hookio.notify(
            f"Forge Protocol: the auditor flagged this response "
            f"({count} finding{'s' if count != 1 else ''} against {mode.name}). "
            "Details go to the next turn."
        )

    bump_audit_blocks(payload.get("cwd"))
    return hookio.block(reason)


# Same policy, separate event: a delegated mode subagent gets audited too.
subagent_stop = stop


# ---------------------------------------------------------------------------
# SessionEnd
# ---------------------------------------------------------------------------

def session_end(payload: dict[str, Any]) -> dict[str, Any]:
    """Surface the mode's closing reflection prompt."""
    if _suppressed():
        return {}

    _sm, session, mode = _session_and_mode(payload)
    if mode is None:
        return {}

    prompt = get_session_end_prompt(mode)
    if not prompt:
        return {}

    return hookio.notify(f"Forge Protocol — {mode.name} reflection: {prompt}")


__all__ = [
    "requested_mode",
    "bash_write_intent",
    "session_start",
    "user_prompt_submit",
    "pre_tool_use",
    "stop",
    "subagent_stop",
    "session_end",
    "load_modes",
    "resolve_session_id",
    "WRITE_TOOLS",
    "THINKING_MODES",
]

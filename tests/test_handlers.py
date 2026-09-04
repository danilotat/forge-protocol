"""Tests for the Codex and Claude Code hook policy in `forge_cc.handlers`.

Replaces the old `test_plugin.py`. Under Hermes the protocol exposed nine
tools the orchestrator could choose to call; the host hooks run the
same logic from hooks, unconditionally. Each handler is a plain
`dict -> dict` function, so these tests drive them with payload dicts instead
of spawning either host.

Every test points `FORGE_STATE_DIR` at a tmp dir and disables the auditor, so
nothing writes to `~/.forge-state/` and nothing spawns a `claude` subprocess.
Tests that are specifically about auditing inject a fake `lib.auditor`
function rather than letting the real transport run.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import time

import pytest

from forge_cc import handlers, hookio, paths
from lib import auditor as aud
from lib.auditor import AuditResult, RuleViolation
from lib.state import StateManager

ALL_HANDLERS = [
    pytest.param(handlers.session_start, id="session_start"),
    pytest.param(handlers.user_prompt_submit, id="user_prompt_submit"),
    pytest.param(handlers.pre_tool_use, id="pre_tool_use"),
    pytest.param(handlers.stop, id="stop"),
    pytest.param(handlers.subagent_stop, id="subagent_stop"),
    pytest.param(handlers.session_end, id="session_end"),
]

THINKING_MODES = ["forge", "anvil", "crucible"]
WRITE_TOOLS = ["Write", "Edit", "MultiEdit", "NotebookEdit"]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """State in a tmp dir, auditor off, no inherited env surprises."""
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")
    for name in (
        aud.CHILD_ENV_VAR,
        "FORGE_SESSION_ID",
        "FORGE_MODES_DIR",
        "FORGE_INPUT_BLOCK",
        "FORGE_OUTPUT_BLOCK",
        "FORGE_INPUT_AUDIT_ALWAYS",
        "FORGE_HOOK_DEBUG",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _session(session_id: str, mode: str = "executor", **fields):
    """Create a session on disk in the given mode."""
    sm = StateManager()
    session = sm.create_session(session_id, initial_mode=mode)
    if fields:
        for key, value in fields.items():
            setattr(session, key, value)
        sm._write_session(session)
    return session


def _load(session_id: str):
    return StateManager().get_session(session_id)


def _context(output: dict) -> str:
    specific = output.get("hookSpecificOutput") or {}
    return specific.get("additionalContext") or ""


def _transcript(tmp_path, text: str) -> str:
    path = tmp_path / "transcript.jsonl"
    path.write_text(
        json.dumps({
            "type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
        }) + "\n",
        encoding="utf-8",
    )
    return str(path)


# ---------------------------------------------------------------------------
# SessionStart
# ---------------------------------------------------------------------------

def test_session_start_injects_mode_and_cli_path(isolated_env):
    out = handlers.session_start({"session_id": "s-start", "cwd": str(isolated_env)})

    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "SessionStart"
    context = specific["additionalContext"]
    assert "Forge Protocol active" in context
    assert "Executor Mode" in context        # default mode's display name
    assert "`executor`" in context
    assert "Mode source: **default**" in context
    assert "FORGE_CLI:" in context
    assert str(paths.cli_path()) in context


def test_session_start_records_the_session_pointer(isolated_env):
    handlers.session_start({"session_id": "s-pointer", "cwd": str(isolated_env)})

    # The `forge` CLI gets no session id from the host, so it reads this
    # pointer back. Both the cwd-keyed entry and the _last fallback must work.
    assert paths.get_current_session(str(isolated_env)) == "s-pointer"
    assert paths.get_current_session() == "s-pointer"
    assert paths.get_current_session("/some/other/dir") == "s-pointer"


def test_session_start_in_forge_mode_announces_enforcement(isolated_env):
    _session("s-forge", "forge")

    context = _context(handlers.session_start({"session_id": "s-forge", "cwd": str(isolated_env)}))

    assert "Forge Mode" in context
    for tool in WRITE_TOOLS:
        assert tool in context
    # The mode's soul is injected too, not just the announcement.
    assert "You are" in context


def test_session_start_shows_audit_reminders(isolated_env):
    _session("s-reminders", "executor")

    context = _context(handlers.session_start({"session_id": "s-reminders"}))

    assert "Audit reminders" in context
    assert "canary" in context.lower()


# Claude Code drops a hook's `additionalContext` once it grows past roughly
# 10 KiB, replacing the whole thing with a 2 KB `<persisted-output>` preview —
# and the hook still exits 0, so an oversized soul silently loses its routing
# contract instead of failing loudly. The ceiling is unpublished; what is
# measured is that 9,552 chars reached the model intact and 10,732 did not,
# truncated just before the orchestrator's routing sequence. Hold the line
# above the known-good size and well under the known-bad one. The four mode
# souls are ~6.2 KB each and research-backed, so the orchestrator soul is the
# part that has to stay small.
HOST_CONTEXT_BUDGET = 9600


@pytest.mark.parametrize("mode", ["executor", *THINKING_MODES])
def test_session_start_context_fits_the_host_injection_budget(isolated_env, mode):
    """Worst case: every audit overdue, so the reminder block is at its longest."""
    _session("s-budget", mode, created_at=time.time() - 400 * 86400)

    context = _context(
        handlers.session_start({"session_id": "s-budget", "cwd": str(isolated_env)})
    )

    assert "Mandatory routing sequence" in context, (
        "the routing contract has to survive into the injected context"
    )
    assert len(context) <= HOST_CONTEXT_BUDGET, (
        f"{mode} SessionStart context is {len(context)} chars; past ~10 KiB the "
        "host truncates it to a 2 KB preview and the orchestrator loses its "
        "routing instructions entirely"
    )


# ---------------------------------------------------------------------------
# UserPromptSubmit — message counting
# ---------------------------------------------------------------------------

def test_user_prompt_submit_increments_by_exactly_one(isolated_env):
    _session("s-count", "executor")

    for expected in (1, 2, 3):
        handlers.user_prompt_submit({"session_id": "s-count", "prompt": "hello"})
        assert _load("s-count").message_count == expected


def test_user_prompt_submit_counts_in_thinking_modes_too(isolated_env):
    _session("s-count-forge", "forge")

    handlers.user_prompt_submit({"session_id": "s-count-forge", "prompt": "my position is X"})

    assert _load("s-count-forge").message_count == 1


def test_user_prompt_submit_creates_a_session_when_none_exists(isolated_env):
    handlers.user_prompt_submit({"session_id": "s-fresh", "prompt": "hi"})

    session = _load("s-fresh")
    assert session is not None
    assert session.message_count == 1
    assert session.current_mode == "executor"


# ---------------------------------------------------------------------------
# UserPromptSubmit — executor is friction-free
# ---------------------------------------------------------------------------

def test_user_prompt_submit_is_silent_in_executor_mode(isolated_env):
    """Executor's zero overhead is a feature, not an oversight."""
    _session("s-exec", "executor", message_count=99)

    out = handlers.user_prompt_submit({"session_id": "s-exec", "prompt": "rename this variable"})

    assert out == {}


def test_user_prompt_submit_is_silent_for_an_unknown_mode(isolated_env):
    _session("s-unknown", "executor")
    sm = StateManager()
    session = sm.get_session("s-unknown")
    session.current_mode = "not-a-mode"
    sm._write_session(session)

    assert handlers.user_prompt_submit({"session_id": "s-unknown", "prompt": "hi"}) == {}


def test_user_prompt_submit_hands_over_input_rules_when_the_auditor_is_off(isolated_env):
    _session("s-selfeval", "forge")

    context = _context(handlers.user_prompt_submit({
        "session_id": "s-selfeval", "prompt": "microservices?",
    }))

    assert "entry requirements" in context
    assert "articulate their own position" in context


# ---------------------------------------------------------------------------
# UserPromptSubmit — checkpoints
# ---------------------------------------------------------------------------

def test_checkpoint_fires_at_the_mode_interval_then_is_consumed(isolated_env):
    """Forge checkpoints every 5 messages, and only once per interval."""
    _session("s-cp", "forge")
    payload = {"session_id": "s-cp", "prompt": "here is my reasoning"}

    for turn in range(1, 5):
        context = _context(handlers.user_prompt_submit(payload))
        assert "checkpoint is due" not in context, f"fired early on turn {turn}"

    fifth = _context(handlers.user_prompt_submit(payload))
    assert "checkpoint is due" in fifth
    assert _load("s-cp").last_checkpoint_at == 5

    sixth = _context(handlers.user_prompt_submit(payload))
    assert "checkpoint is due" not in sixth, "the checkpoint was not marked consumed"
    assert _load("s-cp").last_checkpoint_at == 5


def test_checkpoint_never_fires_in_executor_mode(isolated_env):
    _session("s-cp-exec", "executor")

    for _ in range(12):
        assert handlers.user_prompt_submit({"session_id": "s-cp-exec", "prompt": "go"}) == {}

    assert _load("s-cp-exec").last_checkpoint_at == 0


def test_anvil_checkpoint_interval_is_three(isolated_env):
    _session("s-cp-anvil", "anvil")
    payload = {"session_id": "s-cp-anvil", "prompt": "here is my draft ..."}

    handlers.user_prompt_submit(payload)
    handlers.user_prompt_submit(payload)
    third = _context(handlers.user_prompt_submit(payload))

    assert "checkpoint is due" in third


# ---------------------------------------------------------------------------
# UserPromptSubmit — input audit
# ---------------------------------------------------------------------------

def _fake_input_audit(monkeypatch, result):
    monkeypatch.setattr(aud, "is_available", lambda: True)
    calls: list[tuple] = []

    def _audit_input(user_input, rules, **kwargs):
        calls.append((user_input, rules))
        return result

    monkeypatch.setattr(aud, "audit_input", _audit_input)
    return calls


def test_input_audit_violation_is_surfaced_and_logged(isolated_env, monkeypatch):
    calls = _fake_input_audit(monkeypatch, AuditResult(
        compliant=False,
        violations=[RuleViolation(
            rule="User must articulate their own position",
            kind="input",
            reason="Only a bare topic was submitted.",
        )],
        auditor_model="fake",
    ))
    _session("s-in", "forge")

    out = handlers.user_prompt_submit({"session_id": "s-in", "prompt": "microservices?"})

    assert len(calls) == 1
    context = _context(out)
    assert "entry requirements are not met" in context
    assert "Only a bare topic was submitted." in context

    violations = _load("s-in").violations
    assert len(violations) == 1
    assert violations[0].violation_type == "input"


def test_input_audit_can_hard_block(isolated_env, monkeypatch):
    _fake_input_audit(monkeypatch, AuditResult(
        compliant=False,
        violations=[RuleViolation(rule="state a position", kind="input", reason="missing")],
        auditor_model="fake",
    ))
    monkeypatch.setenv("FORGE_INPUT_BLOCK", "1")
    _session("s-in-block", "forge")

    out = handlers.user_prompt_submit({"session_id": "s-in-block", "prompt": "microservices?"})

    assert out["decision"] == "block"
    assert "entry requirements are not met" in out["reason"]


def test_input_audit_failure_does_not_block(isolated_env, monkeypatch):
    """A broken auditor degrades to self-evaluation, never to a wall."""
    _fake_input_audit(monkeypatch, AuditResult(
        compliant=True, violations=[], auditor_model="fake", error="RuntimeError",
    ))
    _session("s-in-err", "forge")

    out = handlers.user_prompt_submit({"session_id": "s-in-err", "prompt": "my position is X"})

    assert "decision" not in out
    assert _load("s-in-err").violations == []


def test_input_audit_runs_only_on_the_first_turn_in_a_mode(isolated_env, monkeypatch):
    calls = _fake_input_audit(monkeypatch, AuditResult(compliant=True, auditor_model="fake"))
    _session("s-in-once", "forge")
    payload = {"session_id": "s-in-once", "prompt": "my position is X"}

    handlers.user_prompt_submit(payload)
    handlers.user_prompt_submit(payload)
    handlers.user_prompt_submit(payload)

    assert len(calls) == 1, "entry rules are entry rules; auditing every turn is waste"


# ---------------------------------------------------------------------------
# PreToolUse — the write lock
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", THINKING_MODES)
@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tools_are_denied_in_thinking_modes(isolated_env, mode, tool):
    session_id = f"s-deny-{mode}-{tool}"
    _session(session_id, mode)

    out = handlers.pre_tool_use({"session_id": session_id, "tool_name": tool})

    specific = out["hookSpecificOutput"]
    assert specific["hookEventName"] == "PreToolUse"
    assert specific["permissionDecision"] == "deny"

    reason = specific["permissionDecisionReason"]
    assert tool in reason
    mode_name = handlers.load_modes()[mode].name
    assert mode_name in reason, f"the denial must name the mode; got: {reason}"
    assert "executor-mode" in reason  # and offer the way out


@pytest.mark.parametrize("tool", WRITE_TOOLS)
def test_write_tools_are_allowed_in_executor_mode(isolated_env, tool):
    _session("s-allow", "executor")

    assert handlers.pre_tool_use({"session_id": "s-allow", "tool_name": tool}) == {}


def test_codex_apply_patch_is_denied_in_thinking_modes(isolated_env):
    _session("s-codex-patch", "forge")

    out = handlers.pre_tool_use({
        "session_id": "s-codex-patch",
        "tool_name": "apply_patch",
        "tool_input": {"command": "*** Begin Patch"},
    })

    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "apply_patch" in out["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("mode", THINKING_MODES + ["executor"])
def test_read_is_never_blocked(isolated_env, mode):
    session_id = f"s-read-{mode}"
    _session(session_id, mode)

    assert handlers.pre_tool_use({"session_id": session_id, "tool_name": "Read"}) == {}


@pytest.mark.parametrize("tool", ["Read", "Grep", "Glob", "Bash", "WebFetch", "TodoWrite"])
def test_non_write_tools_pass_through_in_forge_mode(isolated_env, tool):
    _session("s-passthrough", "forge")

    assert handlers.pre_tool_use({"session_id": "s-passthrough", "tool_name": tool}) == {}


def test_a_denied_tool_is_logged_as_a_violation(isolated_env):
    _session("s-deny-log", "forge")

    handlers.pre_tool_use({"session_id": "s-deny-log", "tool_name": "Write"})

    violations = _load("s-deny-log").violations
    assert len(violations) == 1
    assert violations[0].mode == "forge"
    assert violations[0].violation_type == "output"
    assert violations[0].rule_id == "tool:Write"
    assert "Write" in violations[0].message


def test_missing_tool_name_is_a_no_op(isolated_env):
    _session("s-noname", "forge")

    assert handlers.pre_tool_use({"session_id": "s-noname"}) == {}
    assert _load("s-noname").violations == []


# ---------------------------------------------------------------------------
# Stop — the output audit
# ---------------------------------------------------------------------------

def _fake_output_audit(monkeypatch, result):
    calls: list[tuple] = []

    def _audit_output(response, rules, **kwargs):
        calls.append((response, rules))
        return result

    monkeypatch.setattr(aud, "audit_output", _audit_output)
    return calls


_VIOLATION_AUDIT = AuditResult(
    compliant=False,
    violations=[
        RuleViolation(
            rule="Provide direct answers to thinking questions",
            kind="forbidden",
            quote="You should use microservices.",
            reason="That is a direct answer.",
        ),
        RuleViolation(
            rule="Every response must contain at least one question",
            kind="required_missing",
            reason="No question was asked.",
        ),
    ],
    auditor_model="fake-auditor",
)


def test_stop_is_a_no_op_when_stop_hook_active(isolated_env, monkeypatch):
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    """The infinite-loop guard.

    A blocking Stop hook sends the agent back for another turn, which fires
    Stop again. Without this check the session would bounce between "revise"
    and "still not compliant" forever, so the guard must come before anything
    that could produce a block — including the audit call itself.
    """
    calls = _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-loop", "forge")
    payload = {
        "session_id": "s-loop",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
        "stop_hook_active": True,
    }

    assert handlers.stop(payload) == {}
    assert calls == [], "the audit must not even run once the hook is already active"
    assert _load("s-loop").violations == []

    # Sanity check that the same payload *would* block without the flag.
    payload["stop_hook_active"] = False
    assert handlers.stop(payload)["decision"] == "block"


def test_stop_is_a_no_op_in_executor_mode(isolated_env, monkeypatch):
    calls = _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-stop-exec", "executor")

    out = handlers.stop({
        "session_id": "s-stop-exec",
        "transcript_path": _transcript(isolated_env, "Renamed the variable."),
    })

    assert out == {}
    assert calls == []


def test_stop_blocks_and_logs_when_the_audit_finds_violations(isolated_env, monkeypatch):
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-stop-block", "forge")

    out = handlers.stop({
        "session_id": "s-stop-block",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
    })

    assert out["decision"] == "block"
    reason = out["reason"]
    assert "fake-auditor" in reason
    assert "Forge Mode" in reason
    assert "Provide direct answers to thinking questions" in reason
    assert "Every response must contain at least one question" in reason
    assert "You should use microservices." in reason

    violations = _load("s-stop-block").violations
    assert len(violations) == 2
    assert {v.violation_type for v in violations} == {"output"}
    assert violations[0].mode == "forge"


def test_stop_prefers_codex_last_assistant_message(isolated_env, monkeypatch):
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    calls = _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-stop-codex", "forge")

    out = handlers.stop({
        "session_id": "s-stop-codex",
        "last_assistant_message": "Codex response",
        "transcript_path": "/unstable/codex/transcript.jsonl",
    })

    assert out["decision"] == "block"
    assert calls[0][0] == "Codex response"


def test_stop_can_warn_instead_of_blocking(isolated_env, monkeypatch):
    _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "0")
    _session("s-stop-warn", "forge")

    out = handlers.stop({
        "session_id": "s-stop-warn",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
    })

    assert "decision" not in out
    assert "systemMessage" in out
    assert len(_load("s-stop-warn").violations) == 2


def test_stop_does_not_block_when_the_audit_errors(isolated_env, monkeypatch):
    """A failing auditor must never interfere with the user's session."""
    _fake_output_audit(monkeypatch, AuditResult(
        compliant=True,
        violations=[],
        auditor_model="fake-auditor",
        error="RuntimeError",
    ))
    _session("s-stop-err", "forge")

    out = handlers.stop({
        "session_id": "s-stop-err",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
    })

    assert out == {}
    assert _load("s-stop-err").violations == []


def test_stop_does_not_block_when_an_errored_audit_still_lists_violations(
    isolated_env, monkeypatch
):
    """`error` wins over `violations`: a half-parsed audit is not evidence."""
    _fake_output_audit(monkeypatch, AuditResult(
        compliant=False,
        violations=[RuleViolation(rule="r", kind="forbidden", reason="why")],
        auditor_model="fake-auditor",
        error="JSONDecodeError",
    ))
    _session("s-stop-err2", "forge")

    out = handlers.stop({
        "session_id": "s-stop-err2",
        "transcript_path": _transcript(isolated_env, "anything"),
    })

    assert out == {}
    assert _load("s-stop-err2").violations == []


def test_stop_does_not_block_when_the_audit_is_compliant(isolated_env, monkeypatch):
    _fake_output_audit(monkeypatch, AuditResult(compliant=True, auditor_model="fake-auditor"))
    _session("s-stop-ok", "forge")

    out = handlers.stop({
        "session_id": "s-stop-ok",
        "transcript_path": _transcript(isolated_env, "What's your own read on this?"),
    })

    assert out == {}


def test_stop_is_a_no_op_when_the_auditor_is_disabled(isolated_env):
    """No fake injected: the real (disabled) auditor returns None."""
    _session("s-stop-off", "forge")

    out = handlers.stop({
        "session_id": "s-stop-off",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
    })

    assert out == {}


@pytest.mark.parametrize("transcript", [None, "", "/nonexistent/transcript.jsonl"])
def test_stop_is_a_no_op_without_a_response(isolated_env, monkeypatch, transcript):
    calls = _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-stop-none", "forge")

    assert handlers.stop({"session_id": "s-stop-none", "transcript_path": transcript}) == {}
    assert calls == []


def test_subagent_stop_shares_the_stop_policy(isolated_env, monkeypatch):
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    _fake_output_audit(monkeypatch, _VIOLATION_AUDIT)
    _session("s-subagent", "crucible")

    out = handlers.subagent_stop({
        "session_id": "s-subagent",
        "transcript_path": _transcript(isolated_env, "Here are five ideas for you."),
    })

    assert out["decision"] == "block"


# ---------------------------------------------------------------------------
# SessionEnd
# ---------------------------------------------------------------------------

def test_session_end_surfaces_the_reflection_prompt(isolated_env):
    _session("s-end", "forge")

    out = handlers.session_end({"session_id": "s-end"})

    assert "Forge Mode reflection:" in out["systemMessage"]


def test_session_end_is_silent_in_executor_mode(isolated_env):
    _session("s-end-exec", "executor")

    assert handlers.session_end({"session_id": "s-end-exec"}) == {}


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "handler", [h for h in ALL_HANDLERS if h.id != "pre_tool_use"]
)
# `pre_tool_use` is intentionally absent from this list: the suppression guard
# exists to stop the auditor's child re-entering hooks that CALL the auditor,
# and the write-lock does not. Honouring the variable there let one stray
# environment variable switch the write-lock off — see
# tests/test_mode_guard.py::test_the_env_var_cannot_disable_the_write_lock.
def test_every_handler_no_ops_inside_the_auditor_child(isolated_env, monkeypatch, handler):
    """`--safe-mode` already stops the child loading this plugin; belt and braces.

    If these fired inside the auditor's own `claude -p` process, each audit
    would trigger another audit.
    """
    monkeypatch.setenv(aud.CHILD_ENV_VAR, "1")
    _session("s-child", "forge")

    out = handler({
        "session_id": "s-child",
        "cwd": str(isolated_env),
        "prompt": "microservices?",
        "tool_name": "Write",
        "transcript_path": _transcript(isolated_env, "You should use microservices."),
    })

    assert out == {}
    # And nothing was recorded either — no counting, no pointer, no violations.
    session = _load("s-child")
    assert session.message_count == 0
    assert session.violations == []
    assert paths.get_current_session(str(isolated_env)) is None


# ---------------------------------------------------------------------------
# hookio.run — a crashed hook must not take the session down
# ---------------------------------------------------------------------------

def test_run_swallows_a_raising_handler(monkeypatch, capsys):
    def _explode(payload):
        raise RuntimeError("handler blew up")

    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s"}'))

    assert hookio.run(_explode) == 0

    captured = capsys.readouterr()
    assert captured.out == "", "a failed hook must print nothing at all"


def test_run_emits_a_handler_result(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"session_id": "s-run"}'))

    assert hookio.run(lambda payload: {"systemMessage": payload["session_id"]}) == 0

    assert json.loads(capsys.readouterr().out) == {"systemMessage": "s-run"}


def test_run_prints_nothing_for_an_empty_result(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    assert hookio.run(lambda payload: {}) == 0

    assert capsys.readouterr().out == ""


def test_run_survives_a_malformed_payload(monkeypatch, capsys):
    seen: list[dict] = []
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json at all"))

    assert hookio.run(lambda payload: seen.append(payload) or {}) == 0

    assert seen == [{}]
    assert capsys.readouterr().out == ""


# ---------------------------------------------------------------------------
# FORGE_HOOK_TRACE — the tailable trail for debugging a live session
# ---------------------------------------------------------------------------

def _trace_lines(state_dir):
    import json as _json
    from pathlib import Path

    path = Path(state_dir) / "audit" / "hooks.jsonl"
    if not path.exists():
        return []
    return [_json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_trace_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path))
    monkeypatch.delenv("FORGE_HOOK_TRACE", raising=False)
    hookio.run(handlers.session_start)
    assert _trace_lines(tmp_path) == []


def test_trace_records_the_decision(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_HOOK_TRACE", "1")
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")

    import io

    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(json.dumps({"session_id": "t1", "cwd": str(tmp_path)})),
    )
    hookio.run(handlers.session_start)

    lines = _trace_lines(tmp_path)
    assert len(lines) == 1
    assert lines[0]["hook"] == "session_start"
    assert lines[0]["decision"] == "context"
    assert lines[0]["session_id"] == "t1"
    assert "ms" in lines[0]


def test_trace_records_a_crash_without_reraising(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("FORGE_HOOK_TRACE", "1")

    def boom(_payload):
        raise RuntimeError("kaboom")

    boom.__name__ = "boom"
    assert hookio.run(boom) == 0

    lines = _trace_lines(tmp_path)
    assert lines[0]["error"] == "RuntimeError"
    # the message must never reach the trail, same rule as auditor errors
    assert "kaboom" not in json.dumps(lines[0])


def test_trace_failure_never_breaks_the_hook(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_HOOK_TRACE", "1")
    # point the state dir at a file, so the audit/ mkdir must fail
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setenv("FORGE_STATE_DIR", str(blocker))
    assert hookio.run(handlers.session_start) == 0


# ---------------------------------------------------------------------------
# The default output path: one answer, correction carried forward
#
# Blocking on Stop fires after the response has rendered, so it cannot stop
# the user reading a violation — it only appends a second copy of the answer.
# The default therefore notifies and feeds the finding to the next turn.
# ---------------------------------------------------------------------------

def _violating_audit(monkeypatch, rule="Offer a single authoritative recommendation"):
    from lib.auditor import AuditResult, RuleViolation

    monkeypatch.setattr(
        "lib.auditor.audit_output",
        lambda *a, **k: AuditResult(
            compliant=False,
            auditor_model="fake",
            violations=[RuleViolation(rule=rule, kind="forbidden",
                                      quote="Here's what I'd suggest", reason="oracular")],
        ),
    )


def _one_turn_transcript(tmp_path, text="Here's what I'd suggest."):
    path = tmp_path / "carry.jsonl"
    path.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "q"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": text}]}}) + "\n",
        encoding="utf-8")
    return path


def test_default_does_not_block_so_the_answer_is_not_doubled(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("FORGE_OUTPUT_BLOCK", raising=False)
    _violating_audit(monkeypatch)

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "d1"])

    out = handlers.stop({
        "session_id": "d1", "cwd": str(tmp_path),
        "transcript_path": str(_one_turn_transcript(tmp_path)),
        "stop_hook_active": False,
    })

    assert "decision" not in out, "the default must not send the turn back"
    assert "systemMessage" in out
    assert "flagged this response" in out["systemMessage"]


def test_the_finding_is_delivered_on_the_next_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("FORGE_OUTPUT_BLOCK", raising=False)
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "d2"])

    _violating_audit(monkeypatch)
    handlers.stop({
        "session_id": "d2", "cwd": str(tmp_path),
        "transcript_path": str(_one_turn_transcript(tmp_path)),
        "stop_hook_active": False,
    })

    nxt = handlers.user_prompt_submit({"session_id": "d2", "cwd": str(tmp_path),
                                       "prompt": "carry on"})
    context = nxt["hookSpecificOutput"]["additionalContext"]
    assert "flagged your PREVIOUS" in context
    assert "authoritative recommendation" in context
    # it must not invite an apology or a re-answer, which would double the reply
    assert "re-answer" in context

    # and it is consumed, not repeated every turn
    later = handlers.user_prompt_submit({"session_id": "d2", "cwd": str(tmp_path),
                                         "prompt": "again"})
    assert "flagged your PREVIOUS" not in (
        later.get("hookSpecificOutput", {}).get("additionalContext", "")
    )


def test_blocking_is_still_available_when_asked_for(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    _violating_audit(monkeypatch)

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "d3"])

    out = handlers.stop({
        "session_id": "d3", "cwd": str(tmp_path),
        "transcript_path": str(_one_turn_transcript(tmp_path)),
        "stop_hook_active": False,
    })
    assert out.get("decision") == "block"


# ---------------------------------------------------------------------------
# The background audit
#
# In the non-blocking path the verdict is not needed until the next turn, so
# making the Stop hook wait ~4-9s for it is pure latency. It is spawned
# detached instead; measured: 56-68ms for the hook vs 4800-9300ms before.
# ---------------------------------------------------------------------------

def test_stop_returns_immediately_and_spawns_a_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("FORGE_OUTPUT_BLOCK", raising=False)
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "1")
    monkeypatch.setenv("FORGE_AUDITOR_CMD", shutil.which("true") or "true")

    spawned = {}
    monkeypatch.setattr(
        handlers, "_spawn_audit",
        lambda mode, resp, user, cwd: spawned.update(mode=mode, resp=resp, cwd=cwd),
    )

    def must_not_run(*_a, **_k):
        raise AssertionError("the default path must not audit synchronously")

    monkeypatch.setattr("lib.auditor.audit_output", must_not_run)

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "as1"])

    out = handlers.stop({
        "session_id": "as1", "cwd": str(tmp_path),
        "transcript_path": str(_one_turn_transcript(tmp_path)),
        "stop_hook_active": False,
    })

    assert out == {}, "nothing to say: the verdict comes later"
    assert spawned["mode"] == "forge"
    assert "suggest" in spawned["resp"]


def test_blocking_path_still_audits_synchronously(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_OUTPUT_BLOCK", "1")
    _violating_audit(monkeypatch)
    monkeypatch.setattr(
        handlers, "_spawn_audit",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not detach when blocking")),
    )

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "as2"])

    out = handlers.stop({
        "session_id": "as2", "cwd": str(tmp_path),
        "transcript_path": str(_one_turn_transcript(tmp_path)),
        "stop_hook_active": False,
    })
    assert out.get("decision") == "block"


def test_a_background_finding_survives_a_switch_to_executor(tmp_path, monkeypatch):
    """Regression: the finding was consumed after the thinking-mode gate, so
    switching to Executor on the next turn silently swallowed it."""
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")

    from forge_cc import paths
    from forge_cc.cli import main as cli_main

    cli_main(["set-mode", "forge", "--session-id", "as3"])
    paths.set_pending_audit("Forge Protocol — an independent auditor found ...", str(tmp_path))

    out = handlers.user_prompt_submit({
        "session_id": "as3", "cwd": str(tmp_path), "prompt": "/executor-mode",
    })
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "flagged your PREVIOUS" in context
    assert "switched to" in context  # both messages ride along


def test_awaiting_a_finding_gives_up_rather_than_stalling(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_AUDIT_WAIT", "0")

    from forge_cc import paths

    paths.set_audit_inflight(str(tmp_path))  # a worker that never finishes
    assert handlers._await_pending_audit(str(tmp_path)) is None

"""The `forge` CLI — what the slash-command skills shell out to.

Claude Code skills are prompts, not code: they drive state changes by calling
this CLI through the Bash tool. Every subcommand prints one JSON object to
stdout (except `soul`, which prints markdown) so the model can read the result
without parsing prose.

Read/write separation is deliberate. `state`, `checkpoint`, `rules`, `report`
and `canary trend` never mutate anything, so `/forge-status` can show a
dashboard without consuming a pending checkpoint or silently clearing an
overdue audit reminder. Mutation is opt-in: `set-mode`, `canary submit`,
`report --record`, `audit-done`.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from .paths import (
    PLUGIN_ROOT,
    cli_path,
    consume_mode_request,
    ensure_importable,
    get_current_session,
    modes_dir,
    peek_mode_request,
    souls_dir,
    state_dir,
)

#: Modes that apply cognitive friction. Kept in step with
#: forge_cc.handlers.THINKING_MODES.
THINKING_MODES = frozenset({"forge", "anvil", "crucible"})

ensure_importable()

from lib import auditor  # noqa: E402
from lib import canary as canary_module  # noqa: E402
from lib.audit import check_audit_reminders, compute_dependency_report  # noqa: E402
from lib.checkpoints import check_checkpoint, messages_until_checkpoint  # noqa: E402
from lib.modes import VALID_MODE_IDS, Mode, load_all_modes  # noqa: E402
from lib.state import StateManager  # noqa: E402
from lib.validator import get_input_rules, get_output_rules  # noqa: E402


def _emit(payload: dict[str, Any]) -> int:
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


def _fail(message: str) -> int:
    json.dump({"error": message}, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 1


def _modes() -> dict[str, Mode]:
    directory = modes_dir()
    if not directory.is_dir():
        return {}
    try:
        return load_all_modes(directory)
    except (OSError, ValueError, RuntimeError):
        return {}


def _session_id(args: argparse.Namespace) -> str:
    return getattr(args, "session_id", None) or get_current_session() or "default"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_state(args: argparse.Namespace) -> int:
    sm = StateManager()
    session = sm.get_or_create_session(_session_id(args))
    modes = _modes()
    mode = modes.get(session.current_mode)
    reminders = check_audit_reminders(session)

    return _emit({
        "session_id": session.session_id,
        "current_mode": session.current_mode,
        "mode_name": mode.name if mode else session.current_mode,
        "mode_description": mode.description if mode else "",
        "message_count": session.message_count,
        "violation_count": len(session.violations),
        "recent_violations": [
            {"rule_id": v.rule_id, "mode": v.mode, "type": v.violation_type}
            for v in session.violations[-5:]
        ],
        "mode_history": [
            {"mode": e.mode, "messages": e.message_count} for e in session.mode_history
        ],
        "messages_until_checkpoint": (
            messages_until_checkpoint(session, mode) if mode else None
        ),
        "audit_reminders": [
            {"type": r.audit_type, "message": r.message, "overdue_days": r.overdue_days}
            for r in reminders
        ],
    })


def cmd_set_mode(args: argparse.Namespace) -> int:
    modes = _modes()
    if not modes:
        return _fail(f"no mode definitions found in {modes_dir()}")
    if args.mode not in modes:
        return _fail(
            f"invalid mode: {args.mode}. Valid: {', '.join(sorted(modes))}"
        )

    sm = StateManager()
    session = sm.get_or_create_session(_session_id(args))
    previous = session.current_mode

    if previous == args.mode:
        return _emit({
            "previous": previous,
            "current": args.mode,
            "changed": False,
            "description": modes[args.mode].description,
            "message": f"Already in {args.mode} mode.",
        })

    # Dropping out of a thinking mode removes the user's friction, so it takes
    # the user's own say-so. Adding friction never does.
    relaxing = previous in THINKING_MODES and args.mode not in THINKING_MODES
    forced = False
    if relaxing:
        consent = consume_mode_request()
        if consent != args.mode:
            if not args.force:
                return _fail(
                    f"refusing to leave {previous} mode: switching to "
                    f"{args.mode} removes the write-lock and the output audit, "
                    "so it has to be the user's decision. Ask the user to run "
                    f"/{args.mode}-mode themselves. (If you are a human driving "
                    "this CLI directly, pass --force.)"
                )
            forced = True

    session = sm.switch_mode(session.session_id, args.mode)

    if forced:
        # Auditable rather than silent: a forced relaxation shows up in
        # /forge-status and in the quarterly dependency report.
        sm.log_violation(
            session.session_id,
            previous,
            "input",
            "mode:forced-relaxation",
            f"forced switch {previous} -> {args.mode} without a user request",
        )
    mode = modes[args.mode]
    return _emit({
        "previous": previous,
        "current": args.mode,
        "changed": True,
        "description": mode.description,
        "message": f"Switched from {previous} to {args.mode} mode.",
        "input_rules": mode.input_rules,
        "forbidden_behaviors": mode.behaviors.forbidden,
        "write_tools_blocked": args.mode in ("forge", "anvil", "crucible"),
    })


def cmd_rules(args: argparse.Namespace) -> int:
    modes = _modes()
    mode = modes.get(args.mode)
    if mode is None:
        return _fail(f"unknown mode: {args.mode}")

    if args.kind == "input":
        rules = get_input_rules(mode)
        return _emit({
            "mode": rules.mode,
            "mode_name": rules.mode_name,
            "input_rules": rules.rules,
        })

    rules = get_output_rules(mode)
    return _emit({
        "mode": rules.mode,
        "mode_name": rules.mode_name,
        "required_behaviors": rules.required_behaviors,
        "forbidden_behaviors": rules.forbidden_behaviors,
    })


def cmd_checkpoint(args: argparse.Namespace) -> int:
    """Read-only: report whether a checkpoint is due without consuming it.

    The UserPromptSubmit hook is what actually delivers and marks checkpoints.
    If this stamped `last_checkpoint_at`, opening the dashboard would swallow
    a pending checkpoint.
    """
    sm = StateManager()
    session = sm.get_or_create_session(_session_id(args))
    mode = _modes().get(session.current_mode)
    if mode is None:
        return _emit({"due": False, "reason": f"unknown mode: {session.current_mode}"})

    result = check_checkpoint(session, mode)
    return _emit({
        "due": result.due,
        "prompt": result.prompt if result.due else "",
        "messages_until_next": messages_until_checkpoint(session, mode),
        "current_mode": session.current_mode,
        "note": "read-only; the UserPromptSubmit hook delivers checkpoints",
    })


def cmd_canary_list(args: argparse.Namespace) -> int:
    store = canary_module.CanaryStore()
    questions = []
    for question in canary_module.list_canary_questions():
        if args.category and question.get("category") != args.category:
            continue
        trend = canary_module.compute_trend(question["id"], store=store)
        scored = [h for h in trend.history if h.get("overall")]
        question["attempts"] = trend.attempts
        question["scored_attempts"] = len(scored)
        question["unscored_attempts"] = trend.attempts - len(scored)
        question["last_score"] = trend.last_score
        questions.append(question)
    return _emit({"questions": questions})


def _read_response(spec: str) -> str:
    if spec == "-":
        return sys.stdin.read()
    return Path(spec).expanduser().read_text(encoding="utf-8")


def cmd_canary_submit(args: argparse.Namespace) -> int:
    try:
        response = _read_response(args.response_file)
    except OSError as e:
        return _fail(f"could not read response file: {type(e).__name__}")

    if not response.strip():
        return _fail("response is empty")

    try:
        attempt, trend = canary_module.submit_canary(args.prompt_id, response)
    except ValueError as e:
        return _fail(str(e))

    sm = StateManager()
    session = sm.get_or_create_session(_session_id(args))
    sm.update_audit(session.session_id, "canary")

    return _emit({
        "prompt_id": args.prompt_id,
        "attempt": {
            "timestamp": attempt.timestamp,
            "overall": attempt.overall,
            "dimensions": attempt.dimensions,
            "notes": attempt.notes,
            "auditor_model": attempt.auditor_model,
            "error": attempt.error,
        },
        "trend": _trend_dict(trend),
    })


def _trend_dict(trend: canary_module.CanaryTrend) -> dict[str, Any]:
    return {
        "attempts": trend.attempts,
        "last_score": trend.last_score,
        "prev_score": trend.prev_score,
        "change_vs_prev": trend.change_vs_prev,
        "mean_last_5": trend.mean_last_5,
        "slope_per_attempt": trend.slope_per_attempt,
    }


def cmd_canary_trend(args: argparse.Namespace) -> int:
    if canary_module.get_canary_question_by_id(args.prompt_id) is None:
        return _fail(f"unknown canary prompt_id: {args.prompt_id}")
    trend = canary_module.compute_trend(args.prompt_id)
    return _emit({"prompt_id": args.prompt_id, "trend": _trend_dict(trend)})


def cmd_report(args: argparse.Namespace) -> int:
    sm = StateManager()
    report = compute_dependency_report(sm)

    recorded = False
    if args.record:
        session = sm.get_or_create_session(_session_id(args))
        sm.update_audit(session.session_id, "dependency")
        recorded = True

    return _emit({
        "total_sessions": report.total_sessions,
        "total_messages": report.total_messages,
        "mode_ratios": {
            "forge": report.mode_ratios.forge,
            "anvil": report.mode_ratios.anvil,
            "crucible": report.mode_ratios.crucible,
            "executor": report.mode_ratios.executor,
        },
        "total_violations": report.total_violations,
        "assessment": report.assessment,
        "recorded_as_completed": recorded,
    })


def cmd_audit_done(args: argparse.Namespace) -> int:
    """Mark an audit as completed so its reminder clears.

    `canary submit` and `report --record` stamp their own audits; this exists
    for the monthly stress test, which is an offline exercise with no other
    way to say "I did it".
    """
    sm = StateManager()
    session = sm.get_or_create_session(_session_id(args))
    sm.update_audit(session.session_id, args.audit_type)
    refreshed = sm.get_session(session.session_id)
    reminders = check_audit_reminders(refreshed) if refreshed else []
    return _emit({
        "audit_type": args.audit_type,
        "recorded": True,
        "remaining_reminders": [r.audit_type for r in reminders],
    })


def cmd_soul(args: argparse.Namespace) -> int:
    mode = _modes().get(args.mode)
    if mode is None:
        sys.stderr.write(f"unknown mode: {args.mode}\n")
        return 1
    try:
        sys.stdout.write(mode.load_system_prompt(PLUGIN_ROOT))
    except (OSError, ValueError) as e:
        sys.stderr.write(f"could not load soul: {type(e).__name__}\n")
        return 1
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Environment sanity check — the answer to 'why isn't the auditor running'."""
    modes = _modes()
    cmd = auditor.cli_path()
    resolved = shutil.which(cmd)

    try:
        import yaml  # noqa: F401
        pyyaml = True
    except ImportError:
        pyyaml = False

    json_twins = sorted(p.stem for p in modes_dir().glob("*.json"))

    return _emit({
        "plugin_root": str(PLUGIN_ROOT),
        "forge_cli": str(cli_path()),
        "modes_dir": str(modes_dir()),
        "souls_dir": str(souls_dir()),
        "state_dir": str(state_dir()),
        "modes_loaded": sorted(modes),
        "modes_expected": sorted(VALID_MODE_IDS),
        "pyyaml_available": pyyaml,
        "mode_json_twins": json_twins,
        "auditor": {
            "enabled": auditor.is_enabled(),
            "available": auditor.is_available(),
            "model": auditor.model_name(),
            "command": cmd,
            "resolved_command": resolved,
            "timeout_seconds": auditor.timeout_seconds(),
            "requires_api_key": False,
        },
        "current_session": get_current_session(),
        "pending_mode_request": peek_mode_request(),
    })


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge Protocol state and audit CLI (Claude Code port).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def with_session(p: argparse.ArgumentParser) -> argparse.ArgumentParser:
        p.add_argument("--session-id", help="override the active session id")
        return p

    with_session(sub.add_parser("state", help="print session state (read-only)")).set_defaults(
        func=cmd_state
    )

    p_set = with_session(sub.add_parser("set-mode", help="switch the active mode"))
    p_set.add_argument("mode", help="forge | anvil | crucible | executor")
    p_set.add_argument(
        "--force",
        action="store_true",
        help="leave a thinking mode without a user request (logged as a violation)",
    )
    p_set.set_defaults(func=cmd_set_mode)

    p_rules = sub.add_parser("rules", help="print a mode's rules (read-only)")
    p_rules.add_argument("mode")
    p_rules.add_argument("--kind", choices=["input", "output"], default="output")
    p_rules.set_defaults(func=cmd_rules)

    with_session(
        sub.add_parser("checkpoint", help="is a checkpoint due? (read-only)")
    ).set_defaults(func=cmd_checkpoint)

    p_canary = sub.add_parser("canary", help="canary skill tracking")
    canary_sub = p_canary.add_subparsers(dest="canary_command", required=True)

    p_cl = canary_sub.add_parser("list", help="list canary prompts with attempt counts")
    p_cl.add_argument("--category")
    p_cl.set_defaults(func=cmd_canary_list)

    p_cs = with_session(canary_sub.add_parser("submit", help="score an unassisted answer"))
    p_cs.add_argument("prompt_id")
    p_cs.add_argument(
        "--response-file",
        required=True,
        help="path to the user's unassisted answer, or - for stdin",
    )
    p_cs.set_defaults(func=cmd_canary_submit)

    p_ct = canary_sub.add_parser("trend", help="score trend for one prompt (read-only)")
    p_ct.add_argument("prompt_id")
    p_ct.set_defaults(func=cmd_canary_trend)

    p_report = with_session(
        sub.add_parser("report", help="mode-usage dependency report (read-only by default)")
    )
    p_report.add_argument(
        "--record",
        action="store_true",
        help="also stamp the quarterly audit as completed",
    )
    p_report.set_defaults(func=cmd_report)

    p_done = with_session(
        sub.add_parser("audit-done", help="mark an audit completed so its reminder clears")
    )
    p_done.add_argument("audit_type", choices=["canary", "stress_test", "dependency"])
    p_done.set_defaults(func=cmd_audit_done)

    p_soul = sub.add_parser("soul", help="print a mode's system prompt")
    p_soul.add_argument("mode")
    p_soul.set_defaults(func=cmd_soul)

    sub.add_parser("doctor", help="environment sanity check").set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

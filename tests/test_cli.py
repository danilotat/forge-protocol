"""Tests for the `forge` CLI in `forge_cc.cli`.

Claude Code skills are prompts, not code — they change protocol state by
shelling out to this CLI and reading the JSON it prints. So the contract under
test is twofold: the JSON shape each subcommand emits, and the read/write
separation. `state`, `rules`, `checkpoint`, `report` and `canary trend` are
read-only; only `set-mode`, `canary submit`, `report --record` and
`audit-done` may mutate anything. `/forge-status` opens a dashboard on every
turn, and a dashboard that silently consumed a pending checkpoint or cleared
an overdue audit reminder would quietly defeat the protocol.

The auditor is disabled throughout, so `canary submit` stores an unscored
attempt instead of spawning a `claude` subprocess.
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from forge_cc import cli, paths
from lib import auditor as aud
from lib.state import StateManager


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")
    for name in (aud.CHILD_ENV_VAR, "FORGE_SESSION_ID", "FORGE_MODES_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(capsys, *argv):
    """Run the CLI and return (exit_code, parsed stdout)."""
    code = cli.main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


def _session_file(session_id: str) -> dict:
    path = paths.state_dir() / "sessions" / f"{session_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def test_doctor_reports_the_environment(capsys):
    code, out = _run(capsys, "doctor")

    assert code == 0
    assert out["plugin_root"] == str(paths.PLUGIN_ROOT)
    assert out["forge_cli"] == str(paths.cli_path())
    assert out["modes_dir"] == str(paths.modes_dir())
    assert out["state_dir"] == str(paths.state_dir())
    assert out["modes_loaded"] == ["anvil", "crucible", "executor", "forge"]
    assert out["modes_expected"] == ["anvil", "crucible", "executor", "forge"]
    # Every authored YAML keeps a committed JSON twin for hosts without PyYAML.
    assert out["mode_json_twins"] == out["modes_loaded"]


def test_doctor_reports_the_auditor_needs_no_api_key(capsys):
    code, out = _run(capsys, "doctor")

    assert code == 0
    auditor_info = out["auditor"]
    assert auditor_info["requires_api_key"] is False
    assert auditor_info["enabled"] is False       # this suite disables it
    assert auditor_info["available"] is False
    assert auditor_info["timeout_seconds"] == 60


def test_doctor_sees_an_available_auditor(capsys, tmp_path, monkeypatch):
    fake = tmp_path / "claude"
    fake.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "1")
    monkeypatch.setenv("FORGE_AUDITOR_CMD", str(fake))

    _code, out = _run(capsys, "doctor")

    assert out["auditor"]["enabled"] is True
    assert out["auditor"]["available"] is True
    assert out["auditor"]["command"] == str(fake)


# ---------------------------------------------------------------------------
# state
# ---------------------------------------------------------------------------

def test_state_creates_and_reports_a_session(capsys):
    code, out = _run(capsys, "state", "--session-id", "s1")

    assert code == 0
    assert out["session_id"] == "s1"
    assert out["current_mode"] == "executor"
    assert out["mode_name"] == "Executor Mode"
    assert out["message_count"] == 0
    assert out["violation_count"] == 0
    assert out["recent_violations"] == []
    assert out["messages_until_checkpoint"] is None   # executor has no interval
    assert [r["type"] for r in out["audit_reminders"]] == ["canary"]


def test_state_reflects_mode_and_violations(capsys):
    sm = StateManager()
    sm.create_session("s2", initial_mode="forge")
    sm.increment_messages("s2")
    sm.increment_messages("s2")
    sm.log_violation("s2", "forge", "output", "tool:Write", "Write denied")

    _code, out = _run(capsys, "state", "--session-id", "s2")

    assert out["current_mode"] == "forge"
    assert out["mode_name"] == "Forge Mode"
    assert out["message_count"] == 2
    assert out["violation_count"] == 1
    assert out["recent_violations"][0]["rule_id"] == "tool:Write"
    assert out["messages_until_checkpoint"] == 3      # forge interval is 5
    assert out["mode_history"] == [{"mode": "forge", "messages": 0}]


def test_state_uses_the_session_pointer_when_no_id_is_given(capsys):
    paths.set_current_session("pointed-at", str(paths.state_dir()))

    _code, out = _run(capsys, "state")

    assert out["session_id"] == "pointed-at"


def test_state_is_read_only(capsys):
    sm = StateManager()
    sm.create_session("s-ro", initial_mode="forge")
    sm.increment_messages("s-ro")
    before = _session_file("s-ro")

    _run(capsys, "state", "--session-id", "s-ro")

    assert _session_file("s-ro") == before


# ---------------------------------------------------------------------------
# set-mode
# ---------------------------------------------------------------------------

def test_set_mode_switches(capsys):
    code, out = _run(capsys, "set-mode", "forge", "--session-id", "sm1")

    assert code == 0
    assert out["previous"] == "executor"
    assert out["current"] == "forge"
    assert out["changed"] is True
    assert out["write_tools_blocked"] is True
    assert out["input_rules"]
    assert out["forbidden_behaviors"]
    assert _session_file("sm1")["current_mode"] == "forge"


def test_set_mode_to_executor_does_not_block_write_tools(capsys, tmp_path):
    _run(capsys, "set-mode", "forge", "--session-id", "sm2")

    # Leaving a thinking mode needs the user's own request; see
    # tests/test_mode_guard.py for the gate itself.
    from forge_cc import paths

    paths.set_mode_request("executor", str(tmp_path))
    _code, out = _run(capsys, "set-mode", "executor", "--session-id", "sm2")

    assert out["changed"] is True
    assert out["write_tools_blocked"] is False


def test_set_mode_rejects_an_unknown_mode(capsys):
    code, out = _run(capsys, "set-mode", "wizard", "--session-id", "sm3")

    assert code == 1
    assert "invalid mode" in out["error"]
    assert "forge" in out["error"]


def test_set_mode_is_a_no_op_when_already_in_that_mode(capsys):
    _run(capsys, "set-mode", "anvil", "--session-id", "sm4")
    before = _session_file("sm4")

    code, out = _run(capsys, "set-mode", "anvil", "--session-id", "sm4")

    assert code == 0
    assert out["changed"] is False
    assert out["previous"] == "anvil"
    assert out["current"] == "anvil"
    assert "Already in anvil mode." in out["message"]
    # No second mode_history entry, no fresh timestamps.
    assert _session_file("sm4") == before


# ---------------------------------------------------------------------------
# rules
# ---------------------------------------------------------------------------

def test_rules_output_is_the_default_kind(capsys):
    code, out = _run(capsys, "rules", "forge")

    assert code == 0
    assert out["mode"] == "forge"
    assert out["mode_name"] == "Forge Mode"
    assert out["required_behaviors"]
    assert out["forbidden_behaviors"]
    assert "input_rules" not in out


def test_rules_kind_output(capsys):
    _code, out = _run(capsys, "rules", "crucible", "--kind", "output")

    assert out["mode"] == "crucible"
    assert any("negative space" in b.lower() or b for b in out["forbidden_behaviors"])


def test_rules_kind_input(capsys):
    code, out = _run(capsys, "rules", "anvil", "--kind", "input")

    assert code == 0
    assert out["mode"] == "anvil"
    assert out["mode_name"] == "Anvil Mode"
    assert any("draft" in rule.lower() for rule in out["input_rules"])
    assert "required_behaviors" not in out


def test_rules_input_for_executor_is_empty(capsys):
    _code, out = _run(capsys, "rules", "executor", "--kind", "input")

    assert out["input_rules"] == []


def test_rules_rejects_an_unknown_mode(capsys):
    code, out = _run(capsys, "rules", "wizard")

    assert code == 1
    assert "unknown mode" in out["error"]


# ---------------------------------------------------------------------------
# checkpoint — read-only
# ---------------------------------------------------------------------------

def test_checkpoint_reports_a_due_checkpoint_without_consuming_it(capsys):
    """A real bug risk: `/forge-status` must not swallow a pending checkpoint.

    Only the UserPromptSubmit hook delivers and stamps checkpoints. If this
    command wrote `last_checkpoint_at`, opening the dashboard would cancel the
    checkpoint the user was about to be asked.
    """
    sm = StateManager()
    session = sm.create_session("cp1", initial_mode="forge")
    session.message_count = 10
    sm._write_session(session)
    assert _session_file("cp1")["last_checkpoint_at"] == 0

    code, first = _run(capsys, "checkpoint", "--session-id", "cp1")
    assert code == 0
    assert first["due"] is True
    assert first["prompt"]
    assert first["current_mode"] == "forge"
    assert _session_file("cp1")["last_checkpoint_at"] == 0

    _code, second = _run(capsys, "checkpoint", "--session-id", "cp1")
    assert second["due"] is True, "a read-only check must stay due"
    assert _session_file("cp1")["last_checkpoint_at"] == 0


def test_checkpoint_counts_down_when_not_due(capsys):
    sm = StateManager()
    session = sm.create_session("cp2", initial_mode="forge")
    session.message_count = 2
    sm._write_session(session)

    _code, out = _run(capsys, "checkpoint", "--session-id", "cp2")

    assert out["due"] is False
    assert out["prompt"] == ""
    assert out["messages_until_next"] == 3


def test_checkpoint_in_executor_mode_is_never_due(capsys):
    _code, out = _run(capsys, "checkpoint", "--session-id", "cp3")

    assert out["due"] is False
    assert out["messages_until_next"] is None


def test_checkpoint_with_an_unknown_mode(capsys):
    sm = StateManager()
    session = sm.create_session("cp4")
    session.current_mode = "not-a-mode"
    sm._write_session(session)

    _code, out = _run(capsys, "checkpoint", "--session-id", "cp4")

    assert out["due"] is False
    assert "unknown mode" in out["reason"]


# ---------------------------------------------------------------------------
# canary
# ---------------------------------------------------------------------------

def test_canary_list_includes_attempt_counts(capsys):
    code, out = _run(capsys, "canary", "list")

    assert code == 0
    assert len(out["questions"]) == 5
    for question in out["questions"]:
        assert question["attempts"] == 0
        assert question["scored_attempts"] == 0
        assert question["unscored_attempts"] == 0
        assert question["last_score"] is None
        assert question["prompt"]


def test_canary_list_filters_by_category(capsys):
    _code, out = _run(capsys, "canary", "list", "--category", "writing")

    assert [q["id"] for q in out["questions"]] == ["writing_email_decline"]


def test_canary_list_counts_an_unscored_attempt(capsys, tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("Hi team, I can't make Thursday.", encoding="utf-8")
    _run(capsys, "canary", "submit", "writing_email_decline",
         "--response-file", str(answer), "--session-id", "c1")

    _code, out = _run(capsys, "canary", "list")

    entry = next(q for q in out["questions"] if q["id"] == "writing_email_decline")
    assert entry["attempts"] == 1
    assert entry["scored_attempts"] == 0      # the auditor is off, so unscored
    assert entry["unscored_attempts"] == 1
    assert entry["last_score"] is None


def test_canary_submit_from_a_file(capsys, tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("Hi team,\n\nI have to decline Thursday's review.", encoding="utf-8")

    code, out = _run(capsys, "canary", "submit", "writing_email_decline",
                     "--response-file", str(answer), "--session-id", "c2")

    assert code == 0
    assert out["prompt_id"] == "writing_email_decline"
    # Disabled auditor: the answer is still stored so it can be rescored later.
    assert out["attempt"]["overall"] == 0.0
    assert out["attempt"]["error"] == "auditor_disabled"
    assert out["trend"]["attempts"] == 1
    # Submitting stamps the weekly canary audit, clearing its reminder.
    assert _session_file("c2")["audit_status"]["last_canary"] is not None


def test_canary_submit_from_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("My unassisted answer, typed by hand."))

    code, out = _run(capsys, "canary", "submit", "analysis_failure_modes",
                     "--response-file", "-", "--session-id", "c3")

    assert code == 0
    assert out["trend"]["attempts"] == 1

    store_path = paths.state_dir() / "canary_history.json"
    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored["analysis_failure_modes"][0]["response"] == (
        "My unassisted answer, typed by hand."
    )


def test_canary_submit_rejects_an_empty_response(capsys, tmp_path):
    answer = tmp_path / "blank.txt"
    answer.write_text("   \n\n", encoding="utf-8")

    code, out = _run(capsys, "canary", "submit", "writing_email_decline",
                     "--response-file", str(answer))

    assert code == 1
    assert out["error"] == "response is empty"


def test_canary_submit_rejects_an_unknown_prompt(capsys, tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("something", encoding="utf-8")

    code, out = _run(capsys, "canary", "submit", "nope",
                     "--response-file", str(answer))

    assert code == 1
    assert "unknown canary prompt_id" in out["error"]


def test_canary_submit_reports_an_unreadable_file_by_type_only(capsys, tmp_path):
    code, out = _run(capsys, "canary", "submit", "writing_email_decline",
                     "--response-file", str(tmp_path / "missing.txt"))

    assert code == 1
    # Only the exception type name — never a path or a message body.
    assert out["error"] == "could not read response file: FileNotFoundError"


def test_canary_trend_is_read_only(capsys, tmp_path):
    answer = tmp_path / "answer.txt"
    answer.write_text("An answer.", encoding="utf-8")
    _run(capsys, "canary", "submit", "debugging_mental_model",
         "--response-file", str(answer), "--session-id", "c4")
    before = _session_file("c4")

    code, out = _run(capsys, "canary", "trend", "debugging_mental_model")

    assert code == 0
    assert out["prompt_id"] == "debugging_mental_model"
    assert out["trend"]["attempts"] == 1
    assert out["trend"]["last_score"] is None
    assert _session_file("c4") == before


def test_canary_trend_rejects_an_unknown_prompt(capsys):
    code, out = _run(capsys, "canary", "trend", "nope")

    assert code == 1
    assert "unknown canary prompt_id" in out["error"]


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------

def test_report_does_not_stamp_the_audit_by_default(capsys):
    sm = StateManager()
    sm.create_session("r1", initial_mode="forge")
    sm.increment_messages("r1")

    code, out = _run(capsys, "report", "--session-id", "r1")

    assert code == 0
    assert out["total_sessions"] == 1
    assert out["total_messages"] == 1
    assert out["recorded_as_completed"] is False
    assert out["assessment"]
    assert set(out["mode_ratios"]) == {"forge", "anvil", "crucible", "executor"}
    # The quarterly audit is untouched: a dashboard must not clear a reminder.
    assert _session_file("r1")["audit_status"]["last_dependency_audit"] is None


def test_report_record_stamps_the_audit(capsys):
    sm = StateManager()
    sm.create_session("r2", initial_mode="forge")
    sm.increment_messages("r2")

    code, out = _run(capsys, "report", "--record", "--session-id", "r2")

    assert code == 0
    assert out["recorded_as_completed"] is True
    assert _session_file("r2")["audit_status"]["last_dependency_audit"] is not None


def test_report_with_no_sessions(capsys):
    code, out = _run(capsys, "report")

    assert code == 0
    assert out["total_sessions"] == 0
    assert out["assessment"] == "No sessions found."


# ---------------------------------------------------------------------------
# audit-done
# ---------------------------------------------------------------------------

def _age_session(session_id: str, days: float) -> None:
    """Backdate a session's creation so its audit reminders come due."""
    import time

    sm = StateManager()
    session = sm.create_session(session_id)
    session.created_at = time.time() - days * 24 * 60 * 60
    sm._write_session(session)


def test_audit_done_clears_the_stress_test_reminder(capsys):
    _age_session("a1", days=200)

    _code, before = _run(capsys, "state", "--session-id", "a1")
    assert "stress_test" in [r["type"] for r in before["audit_reminders"]]

    code, out = _run(capsys, "audit-done", "stress_test", "--session-id", "a1")

    assert code == 0
    assert out["audit_type"] == "stress_test"
    assert out["recorded"] is True
    assert "stress_test" not in out["remaining_reminders"]
    # The other overdue audits are untouched — this clears one reminder only.
    assert "canary" in out["remaining_reminders"]
    assert "dependency" in out["remaining_reminders"]
    assert _session_file("a1")["audit_status"]["last_stress_test"] is not None


def test_audit_done_canary_clears_the_canary_reminder(capsys):
    _age_session("a2", days=200)

    _code, out = _run(capsys, "audit-done", "canary", "--session-id", "a2")

    assert "canary" not in out["remaining_reminders"]
    assert "stress_test" in out["remaining_reminders"]


def test_audit_done_rejects_an_unknown_audit_type(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["audit-done", "vibes"])
    assert exc.value.code == 2


# ---------------------------------------------------------------------------
# soul
# ---------------------------------------------------------------------------

def test_soul_prints_markdown(capsys):
    code = cli.main(["soul", "forge"])
    out = capsys.readouterr().out

    assert code == 0
    assert out.lstrip().startswith("You are")


def test_soul_rejects_an_unknown_mode(capsys):
    code = cli.main(["soul", "wizard"])
    captured = capsys.readouterr()

    assert code == 1
    assert captured.out == ""
    assert "unknown mode" in captured.err


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def test_a_subcommand_is_required():
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2


def test_canary_requires_a_subcommand():
    with pytest.raises(SystemExit) as exc:
        cli.main(["canary"])
    assert exc.value.code == 2

"""Tests for the two guards that keep a thinking mode from being talked out of.

Both exist because of things a real model actually did on the first live
session test:

1. Denied the `Write` tool, it wrote the file with a shell redirect instead.
2. Denied again, it invoked `/executor-mode` on its own authority, switched
   the session out of Forge mode, and did the work legally.

The second is the serious one: a mode the *model* can leave is not a mode.
"""

from __future__ import annotations

import json

import pytest

from forge_cc import paths
from forge_cc.cli import main as cli_main
from forge_cc.handlers import bash_write_intent, requested_mode, user_prompt_submit


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")
    monkeypatch.delenv("FORGE_SESSION_ID", raising=False)
    monkeypatch.chdir(tmp_path)


def _run(capsys, *argv: str) -> tuple[int, dict]:
    code = cli_main(list(argv))
    out = capsys.readouterr().out
    return code, json.loads(out)


# ---------------------------------------------------------------------------
# requested_mode: did the USER ask, or did the model decide?
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "prompt,expected",
    [
        ("/executor-mode", "executor"),
        ("/forge-mode", "forge"),
        ("/anvil-mode please", "anvil"),
        ("switch me to /crucible-mode", "crucible"),
        ("/EXECUTOR-MODE", "executor"),
        ("write a file for me", None),
        ("use executor mode", None),  # prose is not the slash command
        ("", None),
    ],
)
def test_requested_mode(prompt, expected):
    assert requested_mode(prompt) == expected


def test_user_prompt_submit_records_the_users_request(tmp_path):
    payload = {"session_id": "s1", "cwd": str(tmp_path), "prompt": "/executor-mode"}
    user_prompt_submit(payload)
    assert paths.peek_mode_request(str(tmp_path)) == "executor"


def test_user_prompt_submit_records_nothing_for_an_ordinary_prompt(tmp_path):
    payload = {"session_id": "s1", "cwd": str(tmp_path), "prompt": "just write the file"}
    user_prompt_submit(payload)
    assert paths.peek_mode_request(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# The consent gate on set-mode
# ---------------------------------------------------------------------------

def test_entering_a_thinking_mode_needs_no_consent(capsys):
    code, out = _run(capsys, "set-mode", "forge")
    assert code == 0
    assert out["changed"] is True
    assert out["write_tools_blocked"] is True


def test_leaving_a_thinking_mode_is_refused_without_a_user_request(capsys):
    _run(capsys, "set-mode", "forge")
    code, out = _run(capsys, "set-mode", "executor")
    assert code == 1
    assert "refusing to leave forge mode" in out["error"]
    # and the mode did not actually change
    _code, state = _run(capsys, "state")
    assert state["current_mode"] == "forge"


def test_leaving_is_allowed_once_the_user_asked(capsys, tmp_path):
    _run(capsys, "set-mode", "forge")
    paths.set_mode_request("executor", str(tmp_path))
    code, out = _run(capsys, "set-mode", "executor")
    assert code == 0
    assert out["current"] == "executor"


def test_consent_is_single_use(capsys, tmp_path):
    _run(capsys, "set-mode", "forge")
    paths.set_mode_request("executor", str(tmp_path))
    _run(capsys, "set-mode", "executor")

    # A second escape attempt on the same consent must fail.
    _run(capsys, "set-mode", "forge")
    code, out = _run(capsys, "set-mode", "executor")
    assert code == 1
    assert "refusing to leave" in out["error"]


def test_consent_for_a_different_mode_does_not_authorize_this_one(capsys, tmp_path):
    _run(capsys, "set-mode", "forge")
    paths.set_mode_request("anvil", str(tmp_path))
    code, out = _run(capsys, "set-mode", "executor")
    assert code == 1
    assert "refusing to leave" in out["error"]


def test_lateral_move_between_thinking_modes_is_free(capsys):
    _run(capsys, "set-mode", "forge")
    code, out = _run(capsys, "set-mode", "anvil")
    assert code == 0
    assert out["current"] == "anvil"
    assert out["write_tools_blocked"] is True


def test_force_escapes_but_is_logged_as_a_violation(capsys):
    _run(capsys, "set-mode", "forge")
    code, out = _run(capsys, "set-mode", "executor", "--force")
    assert code == 0
    assert out["current"] == "executor"

    _code, state = _run(capsys, "state")
    assert state["violation_count"] == 1
    assert state["recent_violations"][0]["rule_id"] == "mode:forced-relaxation"


def test_doctor_surfaces_a_pending_request(capsys, tmp_path):
    paths.set_mode_request("executor", str(tmp_path))
    _code, out = _run(capsys, "doctor")
    assert out["pending_mode_request"] == "executor"


# ---------------------------------------------------------------------------
# bash_write_intent: the shell-redirect route
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "echo hello > /tmp/foo.txt",
        "cat draft >> notes.md",
        "echo x >/tmp/y",
        "printf a | tee out.txt",
        "sed -i s/a/b/ file.py",
        "perl -pi -e s/a/b/ f",
        "dd if=a of=b",
        "truncate -s 0 log.txt",
    ],
)
def test_shell_writes_are_detected(command):
    assert bash_write_intent(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "./bin/forge set-mode forge >/dev/null",
        "grep -rn foo . 2>&1",
        "git log --oneline | head",
        "python3 -m pytest -q",
        "ls -la",
        "sed s/a/b/ file.py",  # no -i: reads, prints, writes nothing
        'printf "%s" "answer" | ./bin/forge canary submit x --response-file -',
        "",
        "   ",
    ],
)
def test_read_only_commands_are_allowed(command):
    assert bash_write_intent(command) is None


def test_unbalanced_quotes_do_not_raise():
    # shlex would throw; the detector must degrade, not crash a hook.
    assert bash_write_intent('echo "unterminated') is None
    assert bash_write_intent('echo "unterminated > f.txt') is not None


# ---------------------------------------------------------------------------
# The gate is driven by modes/*.yaml, not a hardcoded mode list
# ---------------------------------------------------------------------------

def test_confirm_switch_is_what_gates_the_transition(capsys, tmp_path, monkeypatch):
    """A custom mode that sets confirm_switch: false is free to leave.

    `transitions` used to be parsed and never read. If this test fails because
    the field went back to being decorative, the consent gate has silently
    become a hardcoded mode list again.
    """
    modes = tmp_path / "modes"
    modes.mkdir()
    souls = tmp_path / "souls"
    souls.mkdir()
    (souls / "loose.md").write_text("A mode nobody needs permission to leave.")
    (souls / "tight.md").write_text("A mode that must be confirmed on exit.")

    def write_mode(mode_id: str, confirm: bool) -> None:
        (modes / f"{mode_id}.json").write_text(
            json.dumps({
                "id": mode_id,
                "name": f"{mode_id.title()} Mode",
                "description": mode_id,
                "system_prompt_file": f"souls/{mode_id}.md",
                "behaviors": {"required": [], "forbidden": []},
                "input_rules": [],
                "metacognitive": {"checkpoint_interval": 0, "prompts": []},
                "transitions": {"confirm_switch": confirm, "allowed_to": ["loose", "tight"]},
            })
        )

    write_mode("loose", False)
    write_mode("tight", True)
    monkeypatch.setenv("FORGE_MODES_DIR", str(modes))

    # tight (confirm_switch) -> loose (no confirm) is a relaxation: gated.
    _run(capsys, "set-mode", "tight")
    code, out = _run(capsys, "set-mode", "loose")
    assert code == 1
    assert "refusing to leave tight mode" in out["error"]

    # loose -> tight tightens, so it needs nothing.
    paths.set_mode_request("loose", str(tmp_path))
    _run(capsys, "set-mode", "loose")
    code, out = _run(capsys, "set-mode", "tight")
    assert code == 0


def test_allowed_to_restricts_the_target(capsys, tmp_path, monkeypatch):
    modes = tmp_path / "modes"
    modes.mkdir()
    souls = tmp_path / "souls"
    souls.mkdir()
    for mode_id, allowed in (("island", []), ("elsewhere", ["island"])):
        (souls / f"{mode_id}.md").write_text("x")
        (modes / f"{mode_id}.json").write_text(
            json.dumps({
                "id": mode_id,
                "name": mode_id,
                "description": mode_id,
                "system_prompt_file": f"souls/{mode_id}.md",
                "behaviors": {"required": [], "forbidden": []},
                "input_rules": [],
                "metacognitive": {"checkpoint_interval": 0, "prompts": []},
                # island declares no onward transitions at all
                "transitions": {"confirm_switch": False, "allowed_to": allowed},
            })
        )
    monkeypatch.setenv("FORGE_MODES_DIR", str(modes))

    _run(capsys, "set-mode", "elsewhere")
    code, out = _run(capsys, "set-mode", "island")
    assert code == 0
    # island's allowed_to is empty, so it does not constrain onward moves
    code, out = _run(capsys, "set-mode", "elsewhere")
    assert code == 0

    # but elsewhere only allows island, so a third mode would be refused
    (modes / "third.json").write_text(
        json.dumps({
            "id": "third", "name": "third", "description": "t",
            "system_prompt_file": "souls/island.md",
            "behaviors": {"required": [], "forbidden": []},
            "input_rules": [],
            "metacognitive": {"checkpoint_interval": 0, "prompts": []},
            "transitions": {"confirm_switch": False, "allowed_to": []},
        })
    )
    code, out = _run(capsys, "set-mode", "third")
    assert code == 1
    assert "does not allow switching to third" in out["error"]


# ---------------------------------------------------------------------------
# The revision cap
#
# `stop_hook_active` is necessary but not sufficient: measured against Claude
# Code 2.1.258, a second block inside the same turn still arrives with the
# flag false. Without our own budget the auditor can demand revision after
# revision at ~7s each, and the user watches the same answer get rewritten.
# ---------------------------------------------------------------------------

def _forge_stop_payload(tmp_path, transcript):
    return {
        "session_id": "cap1",
        "cwd": str(tmp_path),
        "transcript_path": str(transcript),
        "stop_hook_active": False,
    }


def _turn(tmp_path, text="a reply that violates the mode"):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps({"type": "user", "message": {"role": "user", "content": "a prompt"}}) + "\n"
        + json.dumps({"type": "assistant", "message": {"role": "assistant",
                      "content": [{"type": "text", "text": text}]}}) + "\n",
        encoding="utf-8",
    )
    return path


def _always_violates(monkeypatch):
    from lib.auditor import AuditResult, RuleViolation

    monkeypatch.setattr(
        "lib.auditor.audit_output",
        lambda *a, **k: AuditResult(
            compliant=False,
            violations=[RuleViolation(rule="lead with questions", kind="required_missing",
                                      reason="verdict first")],
            auditor_model="fake",
        ),
    )


def test_second_block_in_one_turn_is_refused(capsys, tmp_path, monkeypatch):
    from forge_cc import handlers

    _always_violates(monkeypatch)
    _run(capsys, "set-mode", "forge", "--session-id", "cap1")
    transcript = _turn(tmp_path)
    payload = _forge_stop_payload(tmp_path, transcript)

    first = handlers.stop(payload)
    assert first.get("decision") == "block", "the first violation must block"

    second = handlers.stop(payload)
    assert second == {}, "a second block in the same turn must be refused"


def test_a_new_user_turn_restores_the_budget(capsys, tmp_path, monkeypatch):
    from forge_cc import handlers

    _always_violates(monkeypatch)
    _run(capsys, "set-mode", "forge", "--session-id", "cap1")
    transcript = _turn(tmp_path)
    payload = _forge_stop_payload(tmp_path, transcript)

    assert handlers.stop(payload).get("decision") == "block"
    assert handlers.stop(payload) == {}

    handlers.user_prompt_submit({"session_id": "cap1", "cwd": str(tmp_path), "prompt": "next"})
    assert handlers.stop(payload).get("decision") == "block", "budget should reset per turn"


def test_max_revisions_is_configurable(capsys, tmp_path, monkeypatch):
    from forge_cc import handlers

    _always_violates(monkeypatch)
    monkeypatch.setenv("FORGE_MAX_REVISIONS", "2")
    _run(capsys, "set-mode", "forge", "--session-id", "cap1")
    payload = _forge_stop_payload(tmp_path, _turn(tmp_path))

    assert handlers.stop(payload).get("decision") == "block"
    assert handlers.stop(payload).get("decision") == "block"
    assert handlers.stop(payload) == {}


def test_max_revisions_zero_disables_blocking(capsys, tmp_path, monkeypatch):
    from forge_cc import handlers

    _always_violates(monkeypatch)
    monkeypatch.setenv("FORGE_MAX_REVISIONS", "0")
    _run(capsys, "set-mode", "forge", "--session-id", "cap1")
    payload = _forge_stop_payload(tmp_path, _turn(tmp_path))
    assert handlers.stop(payload) == {}

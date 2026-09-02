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

"""Tests for the auditor's real subprocess transport.

``lib.auditor`` audits by spawning ``claude -p`` and reading a JSON envelope
back off stdout. These tests exercise that code path for real — subprocess,
argv, stdout parsing, exit codes — by dropping a **fake** ``claude``
executable in a tmp dir and pointing ``FORGE_AUDITOR_CMD`` at it. Nothing here
runs the real binary or makes a network call.

The argv assertions are not cosmetic. Three flags carry the design of the
port, and dropping (or adding) one silently breaks it:

* ``--safe-mode`` keeps the child from loading this plugin's own hooks, which
  would make every audit recurse.
* ``--tools ""`` keeps the auditor a judge rather than an agent.
* ``--bare`` must stay absent: it forces API-key auth, and reusing Claude
  Code's existing credentials is the entire point of this transport.
"""
from __future__ import annotations

import json
import sys

import pytest

from lib import auditor as aud
from lib.validator import InputRules, OutputRules


# ---------------------------------------------------------------------------
# The fake `claude` executable
# ---------------------------------------------------------------------------
#
# It records the argv and the child-marker env var it was handed, then replays
# a canned stdout/stderr/exit status configured through the environment.

_FAKE_BODY = '''\
import json, os, sys

with open(os.environ["FORGE_FAKE_RECORD"], "w", encoding="utf-8") as f:
    json.dump(
        {
            "argv": sys.argv[1:],
            "child_env": os.environ.get("FORGE_AUDITOR_CHILD"),
        },
        f,
    )

sys.stdout.write(os.environ.get("FORGE_FAKE_STDOUT", ""))
sys.stderr.write(os.environ.get("FORGE_FAKE_STDERR", ""))
raise SystemExit(int(os.environ.get("FORGE_FAKE_EXIT", "0")))
'''


class _FakeClaude:
    def __init__(self, path, record, monkeypatch):
        self.path = path
        self.record = record
        self._monkeypatch = monkeypatch

    def configure(self, *, stdout: str = "", stderr: str = "", exit_code: int = 0) -> None:
        self._monkeypatch.setenv("FORGE_FAKE_STDOUT", stdout)
        self._monkeypatch.setenv("FORGE_FAKE_STDERR", stderr)
        self._monkeypatch.setenv("FORGE_FAKE_EXIT", str(exit_code))

    @property
    def was_invoked(self) -> bool:
        return self.record.exists()

    def recorded(self) -> dict:
        assert self.record.exists(), "the fake claude executable was never invoked"
        return json.loads(self.record.read_text(encoding="utf-8"))

    def argv(self) -> list[str]:
        return self.recorded()["argv"]


@pytest.fixture
def fake_claude(tmp_path, monkeypatch):
    script = tmp_path / "claude"
    script.write_text("#!" + sys.executable + "\n" + _FAKE_BODY, encoding="utf-8")
    script.chmod(0o755)

    record = tmp_path / "invocation.json"
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "1")
    monkeypatch.setenv("FORGE_AUDITOR_CMD", str(script))
    monkeypatch.setenv("FORGE_AUDITOR_MODEL", "test-model")
    monkeypatch.setenv("FORGE_AUDITOR_TIMEOUT", "30")
    monkeypatch.setenv("FORGE_FAKE_RECORD", str(record))
    monkeypatch.delenv(aud.CHILD_ENV_VAR, raising=False)

    fake = _FakeClaude(script, record, monkeypatch)
    fake.configure()
    return fake


def _rules() -> OutputRules:
    return OutputRules(
        mode="forge",
        mode_name="Forge Mode",
        required_behaviors=["ask at least one question"],
        forbidden_behaviors=["provide direct answers"],
    )


def _envelope(**kw) -> str:
    return json.dumps(kw)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_structured_output_is_parsed(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False,
        structured_output={
            "compliant": False,
            "violations": [
                {
                    "rule": "provide direct answers",
                    "kind": "forbidden",
                    "quote": "Use microservices.",
                    "reason": "A direct answer.",
                }
            ],
        },
    ))

    result = aud.audit_output("Use microservices.", _rules())

    assert result is not None
    assert result.error is None
    assert result.compliant is False
    assert result.violations[0].quote == "Use microservices."
    assert result.auditor_model == "test-model"
    assert fake_claude.was_invoked


def test_runner_returns_the_structured_object_directly(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False,
        structured_output={"compliant": True, "violations": []},
    ))

    parsed = aud._cli_runner("sys prompt", "user prompt", aud.OUTPUT_AUDIT_SCHEMA)

    assert parsed == {"compliant": True, "violations": []}


def test_falls_back_to_the_result_string(fake_claude):
    """Structured output may be unavailable; the text result still holds JSON."""
    fake_claude.configure(stdout=_envelope(
        is_error=False,
        result=json.dumps({"compliant": True, "violations": []}),
    ))

    result = aud.audit_output("What do you think?", _rules())

    assert result is not None
    assert result.error is None
    assert result.compliant is True
    assert result.violations == []


def test_structured_output_wins_over_the_result_string(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False,
        structured_output={"compliant": True, "violations": []},
        result=json.dumps({"compliant": False, "violations": [
            {"rule": "r", "kind": "forbidden", "quote": "", "reason": ""}
        ]}),
    ))

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.violations == []


def test_canary_scoring_goes_through_the_same_transport(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False,
        structured_output={
            "dimensions": {"clarity": 4, "depth": 4, "independence": 4},
            "notes": "solid",
        },
    ))

    score = aud.score_canary("Write an email.", "Hi team,")

    assert score.error is None
    assert score.overall == pytest.approx(4.0)
    assert score.notes == "solid"


# ---------------------------------------------------------------------------
# Failure paths — all non-blocking
# ---------------------------------------------------------------------------

def test_is_error_envelope_is_non_blocking(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=True,
        result="Credit balance too low",
    ))

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True, "a failed audit must never block a response"
    assert result.error == "RuntimeError"
    assert "Credit" not in (result.error or "")


def test_non_zero_exit_is_non_blocking(fake_claude):
    fake_claude.configure(
        stdout="",
        stderr="SECRET-STDERR-abc: auth token 12345 rejected",
        exit_code=2,
    )

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "RuntimeError"
    # stderr can hold credentials and tracebacks; it must not ride along.
    assert "SECRET" not in (result.error or "")
    assert "12345" not in (result.error or "")


def test_garbage_on_stdout_is_non_blocking(fake_claude):
    fake_claude.configure(stdout="I'm afraid I can't do that.\n")

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "JSONDecodeError"  # a ValueError subclass
    assert "afraid" not in (result.error or "")


def test_empty_envelope_is_non_blocking(fake_claude):
    """No structured_output and no result — nothing to audit against."""
    fake_claude.configure(stdout=_envelope(is_error=False))

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "ValueError"


def test_non_json_result_string_is_non_blocking(fake_claude):
    fake_claude.configure(stdout=_envelope(is_error=False, result="Sure, looks compliant!"))

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "JSONDecodeError"


def test_timeout_is_non_blocking(fake_claude, monkeypatch):
    """A hung subprocess surfaces as TimeoutExpired, not as a crash."""
    import subprocess

    def _hang(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="claude", timeout=1)

    monkeypatch.setattr(subprocess, "run", _hang)

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "TimeoutExpired"


def test_missing_binary_is_non_blocking(monkeypatch):
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "1")
    monkeypatch.setenv("FORGE_AUDITOR_CMD", "/nonexistent/path/to/claude")
    monkeypatch.delenv(aud.CHILD_ENV_VAR, raising=False)

    assert aud.is_available() is False

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "FileNotFoundError"


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------

def test_build_argv_shape(fake_claude):
    argv = aud.build_argv("SYSTEM TEXT", aud.OUTPUT_AUDIT_SCHEMA, "USER TEXT")

    assert argv[0] == str(fake_claude.path)

    # Headless, one-shot prompt mode.
    assert "-p" in argv
    assert argv[argv.index("-p") + 1] == "USER TEXT"

    # The recursion guard: without --safe-mode the child loads this plugin's
    # hooks and every audit spawns another audit.
    assert "--safe-mode" in argv

    # A judge, not an agent: no filesystem, no bash, no web. The empty string
    # is the value, so assert on the pair rather than on membership.
    assert argv[argv.index("--tools") + 1] == ""

    # Server-side structured output, so the reply is parsed rather than scraped
    # out of prose.
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == aud.OUTPUT_AUDIT_SCHEMA
    assert argv[argv.index("--output-format") + 1] == "json"

    assert argv[argv.index("--system-prompt") + 1] == "SYSTEM TEXT"
    assert argv[argv.index("--model") + 1] == "test-model"

    # --bare must NEVER appear: it forces API-key auth, which would reintroduce
    # the exact dependency this transport exists to remove. It looks like a
    # tidier alternative to --safe-mode; it is not.
    assert "--bare" not in argv


def test_argv_reaches_the_subprocess(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False, structured_output={"compliant": True, "violations": []}
    ))

    aud.audit_output("the audited response", _rules())

    argv = fake_claude.argv()
    assert "-p" in argv
    assert "--safe-mode" in argv
    assert "--bare" not in argv
    assert argv[argv.index("--tools") + 1] == ""
    assert "the audited response" in argv[argv.index("-p") + 1]


def test_input_audit_uses_the_input_schema(fake_claude):
    fake_claude.configure(stdout=_envelope(
        is_error=False, structured_output={"compliant": True, "violations": []}
    ))

    aud.audit_input(
        "here is my position",
        InputRules(mode="forge", mode_name="Forge Mode", rules=["state a position"]),
    )

    argv = fake_claude.argv()
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert schema == aud.INPUT_AUDIT_SCHEMA


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

def test_child_marker_makes_the_auditor_unavailable(fake_claude, monkeypatch):
    monkeypatch.setenv(aud.CHILD_ENV_VAR, "1")
    assert aud.is_enabled() is True
    assert aud.is_available() is False


def test_transport_refuses_to_spawn_inside_its_own_child(fake_claude, monkeypatch):
    monkeypatch.setenv(aud.CHILD_ENV_VAR, "1")

    with pytest.raises(RuntimeError):
        aud._cli_runner("sys", "user", aud.OUTPUT_AUDIT_SCHEMA)

    assert not fake_claude.was_invoked, "the auditor spawned a nested child process"


def test_nested_audit_is_non_blocking(fake_claude, monkeypatch):
    monkeypatch.setenv(aud.CHILD_ENV_VAR, "1")

    result = aud.audit_output("x", _rules())

    assert result is not None
    assert result.compliant is True
    assert result.error == "RuntimeError"
    assert not fake_claude.was_invoked


def test_child_process_gets_the_marker_env_var(fake_claude):
    """Belt and braces alongside --safe-mode: the child sees the marker set."""
    fake_claude.configure(stdout=_envelope(
        is_error=False, structured_output={"compliant": True, "violations": []}
    ))

    aud.audit_output("x", _rules())

    assert fake_claude.recorded()["child_env"] == "1"

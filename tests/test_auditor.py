"""Tests for the adversarial auditor's policy layer.

The auditor now shells out to a headless ``claude -p`` subprocess rather than
using the anthropic SDK, so the injectable seam is a ``Runner`` — a plain
``(system, user, schema) -> dict`` callable that returns the parsed JSON the
model produced and raises on any failure. Everything here injects one, so no
test spawns a process or touches the network. The real transport is covered in
``test_auditor_transport.py``.

The load-bearing contract under test is the never-crash one: whatever a runner
does, ``audit_*`` returns ``compliant=True`` with ``error`` set to the
exception's *type name only*. Error message bodies (stderr, request headers,
prompt echoes) must never reach the caller, because the caller feeds this
straight into user-visible LLM context. See commit 94e32bd.
"""
from __future__ import annotations

import pytest

from lib import auditor as aud
from lib.validator import InputRules, OutputRules


# ---------------------------------------------------------------------------
# Runner doubles
# ---------------------------------------------------------------------------

class _Runner:
    """A runner that returns a canned object and records how it was called."""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple[str, str, dict]] = []

    def __call__(self, system: str, user: str, schema: dict):
        self.calls.append((system, user, schema))
        return self.payload


class _Boom:
    """A runner that always raises. Records calls so we can assert it ran."""

    def __init__(self, exc: BaseException):
        self.exc = exc
        self.calls = 0

    def __call__(self, system: str, user: str, schema: dict):
        self.calls += 1
        raise self.exc


def _enable_auditor(monkeypatch):
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "1")
    monkeypatch.setenv("FORGE_AUDITOR_MODEL", "test-model")


def _output_rules(**kw) -> OutputRules:
    return OutputRules(
        mode=kw.get("mode", "forge"),
        mode_name=kw.get("mode_name", "Forge Mode"),
        required_behaviors=kw.get("required_behaviors", []),
        forbidden_behaviors=kw.get("forbidden_behaviors", []),
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_enabled_by_default(monkeypatch):
    """No API key is needed any more, so the honest default is 'on'."""
    monkeypatch.delenv("FORGE_AUDITOR_ENABLED", raising=False)
    assert aud.is_enabled() is True


def test_disable_requires_an_explicit_falsey_value(monkeypatch):
    for value in ("0", "false", "FALSE", "no", "off", "  Off  "):
        monkeypatch.setenv("FORGE_AUDITOR_ENABLED", value)
        assert aud.is_enabled() is False, value
    for value in ("1", "true", "TRUE", "yes", "on", ""):
        monkeypatch.setenv("FORGE_AUDITOR_ENABLED", value)
        assert aud.is_enabled() is True, value


def test_audit_helpers_return_none_when_disabled(monkeypatch):
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")
    runner = _Runner({"compliant": True, "violations": []})
    assert aud.audit_output("hello", _output_rules(), runner=runner) is None
    assert aud.audit_input(
        "hi",
        InputRules(mode="forge", mode_name="Forge Mode", rules=["articulate"]),
        runner=runner,
    ) is None
    assert runner.calls == []


def test_model_name_default_and_override(monkeypatch):
    monkeypatch.delenv("FORGE_AUDITOR_MODEL", raising=False)
    assert aud.model_name() == "sonnet"
    monkeypatch.setenv("FORGE_AUDITOR_MODEL", "haiku")
    assert aud.model_name() == "haiku"


def test_cli_path_default_and_override(monkeypatch):
    monkeypatch.delenv("FORGE_AUDITOR_CMD", raising=False)
    assert aud.cli_path() == "claude"
    monkeypatch.setenv("FORGE_AUDITOR_CMD", "/opt/bin/claude")
    assert aud.cli_path() == "/opt/bin/claude"


def test_timeout_seconds_default_and_overrides(monkeypatch):
    monkeypatch.delenv("FORGE_AUDITOR_TIMEOUT", raising=False)
    assert aud.timeout_seconds() == 60
    monkeypatch.setenv("FORGE_AUDITOR_TIMEOUT", "5")
    assert aud.timeout_seconds() == 5
    monkeypatch.setenv("FORGE_AUDITOR_TIMEOUT", "not-a-number")
    assert aud.timeout_seconds() == 60
    monkeypatch.setenv("FORGE_AUDITOR_TIMEOUT", "0")
    assert aud.timeout_seconds() == 1  # never a zero timeout


# ---------------------------------------------------------------------------
# audit_output
# ---------------------------------------------------------------------------

def test_audit_output_compliant(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({"compliant": True, "violations": []})
    rules = _output_rules(
        required_behaviors=["ask at least one question"],
        forbidden_behaviors=["provide direct answers"],
    )

    result = aud.audit_output("What's your position on this?", rules, runner=runner)

    assert result is not None
    assert result.compliant is True
    assert result.violations == []
    assert result.error is None
    assert result.auditor_model == "test-model"

    # The rules and the audited text have to reach the prompt, or the audit is
    # judging nothing.
    system, user, schema = runner.calls[0]
    assert "ask at least one question" in user
    assert "provide direct answers" in user
    assert "What's your position on this?" in user
    assert "Forge Mode" in user
    assert "auditor" in system.lower()
    assert schema is aud.OUTPUT_AUDIT_SCHEMA


def test_audit_output_flags_violations(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({
        "compliant": False,
        "violations": [
            {
                "rule": "provide direct answers",
                "kind": "forbidden",
                "quote": "You should use microservices.",
                "reason": "That is a direct answer to a thinking question.",
            }
        ],
    })
    rules = _output_rules(forbidden_behaviors=["provide direct answers"])

    result = aud.audit_output("You should use microservices.", rules, runner=runner)

    assert result is not None
    assert result.compliant is False
    assert result.error is None
    assert len(result.violations) == 1
    v = result.violations[0]
    assert v.rule == "provide direct answers"
    assert v.kind == "forbidden"
    assert "microservices" in v.quote
    assert "direct answer" in v.reason


def test_audit_output_ignores_non_dict_violation_entries(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({"compliant": False, "violations": ["nonsense", None]})
    result = aud.audit_output("x", _output_rules(), runner=runner)
    assert result is not None
    assert result.compliant is False
    assert result.violations == []


def test_audit_output_to_dict_is_json_safe(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({
        "compliant": False,
        "violations": [
            {"rule": "r", "kind": "forbidden", "quote": "q", "reason": "why"}
        ],
    })
    result = aud.audit_output("x", _output_rules(), runner=runner)
    assert result is not None
    payload = result.to_dict()
    assert payload["compliant"] is False
    assert payload["violations"] == [
        {"rule": "r", "kind": "forbidden", "quote": "q", "reason": "why"}
    ]
    assert payload["error"] is None


# ---------------------------------------------------------------------------
# audit_input
# ---------------------------------------------------------------------------

def test_audit_input_short_circuits_with_no_rules(monkeypatch):
    """Executor mode has no entry rules — that must not cost a model call."""
    _enable_auditor(monkeypatch)
    runner = _Runner({"compliant": False, "violations": [{"rule": "nope"}]})

    result = aud.audit_input(
        "anything at all",
        InputRules(mode="executor", mode_name="Executor Mode", rules=[]),
        runner=runner,
    )

    assert result is not None
    assert result.compliant is True
    assert result.violations == []
    assert result.error is None
    assert runner.calls == [], "the runner must not be invoked when there are no rules"


def test_audit_input_flags_fragment_dumping(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({
        "compliant": False,
        "violations": [
            {
                "rule": "User must articulate their own position",
                "kind": "forbidden",   # the model got the kind wrong on purpose
                "quote": "",
                "reason": "User submitted only a vague topic, not a position.",
            }
        ],
    })
    rules = InputRules(
        mode="forge",
        mode_name="Forge Mode",
        rules=["User must articulate their own position"],
    )

    result = aud.audit_input("microservices?", rules, runner=runner)

    assert result is not None
    assert result.compliant is False
    # audit_input normalizes kind regardless of what the model said.
    assert result.violations[0].kind == "input"
    _system, user, schema = runner.calls[0]
    assert "User must articulate their own position" in user
    assert "microservices?" in user
    assert schema is aud.INPUT_AUDIT_SCHEMA


# ---------------------------------------------------------------------------
# score_canary
# ---------------------------------------------------------------------------

def test_score_canary_averages_dimensions(monkeypatch):
    _enable_auditor(monkeypatch)
    runner = _Runner({
        "dimensions": {"clarity": 4, "depth": 3, "independence": 5},
        "notes": "Clear voice; the second paragraph is templated.",
    })

    score = aud.score_canary("Write an email.", "Hi team,\n\nProposal attached.", runner=runner)

    assert score.overall == pytest.approx((4 + 3 + 5) / 3, abs=0.01)
    assert score.dimensions == {"clarity": 4, "depth": 3, "independence": 5}
    assert "templated" in score.notes
    assert score.auditor_model == "test-model"
    assert score.error is None
    _system, user, schema = runner.calls[0]
    assert "Write an email." in user
    assert "Proposal attached." in user
    assert schema is aud.CANARY_SCORE_SCHEMA


def test_score_canary_with_no_dimensions_scores_zero(monkeypatch):
    _enable_auditor(monkeypatch)
    score = aud.score_canary("p", "r", runner=_Runner({"dimensions": {}, "notes": "n"}))
    assert score.overall == 0.0
    assert score.dimensions == {}
    assert score.error is None


def test_score_canary_disabled_returns_error(monkeypatch):
    monkeypatch.setenv("FORGE_AUDITOR_ENABLED", "0")
    runner = _Runner({"dimensions": {"clarity": 5}, "notes": ""})

    score = aud.score_canary("prompt", "response", runner=runner)

    assert score.overall == 0.0
    assert score.dimensions == {}
    assert score.error == "auditor_disabled"
    assert runner.calls == []


# ---------------------------------------------------------------------------
# Failure matrix — the never-crash / never-leak contract
# ---------------------------------------------------------------------------
#
# `error` carries the exception TYPE NAME and nothing else. An exception's
# message can hold a subprocess's stderr, an auth failure body, or an echo of
# the audited prompt, and the caller pipes `error` into text the model (and so
# the user) sees. Commit 94e32bd exists because that leak happened once.

_SECRET = "SECRET-STDERR-abc"

FAILING_RUNNERS = [
    pytest.param(_Boom(RuntimeError(_SECRET)), "RuntimeError", id="runtime-error"),
    pytest.param(_Boom(TimeoutError(_SECRET)), "TimeoutError", id="timeout-error"),
    pytest.param(_Boom(ValueError(_SECRET)), "ValueError", id="value-error"),
    # A runner that returns something that is not a dict: the parse below blows
    # up on `.get`, which must be caught like any other failure.
    pytest.param(lambda s, u, sc: ["not", "a", "dict"], "AttributeError", id="non-dict-return"),
]


@pytest.mark.parametrize("runner,expected_error", FAILING_RUNNERS)
def test_audit_output_never_crashes(monkeypatch, runner, expected_error):
    _enable_auditor(monkeypatch)
    result = aud.audit_output("a response", _output_rules(), runner=runner)

    assert result is not None
    assert result.compliant is True, "an audit failure must never block a response"
    assert result.violations == []
    assert result.error == expected_error
    assert _SECRET not in (result.error or "")
    assert "SECRET" not in (result.error or "")
    assert result.raw_response == ""


@pytest.mark.parametrize("runner,expected_error", FAILING_RUNNERS)
def test_audit_input_never_crashes(monkeypatch, runner, expected_error):
    _enable_auditor(monkeypatch)
    rules = InputRules(mode="forge", mode_name="Forge Mode", rules=["say something"])

    result = aud.audit_input("hi", rules, runner=runner)

    assert result is not None
    assert result.compliant is True
    assert result.violations == []
    assert result.error == expected_error
    assert "SECRET" not in (result.error or "")


@pytest.mark.parametrize("runner,expected_error", FAILING_RUNNERS)
def test_score_canary_never_crashes(monkeypatch, runner, expected_error):
    _enable_auditor(monkeypatch)
    score = aud.score_canary("prompt", "response", runner=runner)

    assert score.overall == 0.0
    assert score.dimensions == {}
    assert score.error == expected_error
    assert "SECRET" not in (score.error or "")


def test_error_string_never_carries_the_exception_message(monkeypatch):
    """One explicit, non-parametrized statement of the sanitization rule."""
    _enable_auditor(monkeypatch)
    boom = _Boom(RuntimeError("SECRET-STDERR-abc: traceback from claude stderr"))

    result = aud.audit_output("a response", _output_rules(), runner=boom)

    assert boom.calls == 1, "the runner really was called"
    assert result is not None
    assert result.error == "RuntimeError"
    assert "SECRET" not in result.error
    assert "traceback" not in result.error
    assert "stderr" not in result.error
    # Nor may it leak through the serialized form the tools hand to the model.
    assert "SECRET" not in str(result.to_dict())


def test_keyboard_interrupt_is_not_swallowed(monkeypatch):
    """`except Exception` is deliberate: Ctrl-C must still reach the user."""
    _enable_auditor(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        aud.audit_output("x", _output_rules(), runner=_Boom(KeyboardInterrupt()))

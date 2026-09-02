"""Adversarial auditor — a second model evaluates compliance.

The Forge Protocol's original design asks the SAME orchestrator LLM that
produced a response to judge whether it complied with the mode's rules.
LLMs are poor at that kind of self-judgment; they readily rubber-stamp
their own work. This module fixes that by asking a *different* model
instance to audit compliance independently.

Transport: a headless ``claude -p`` subprocess. That reuses whatever
credentials Claude Code already has, so the auditor needs **no API key**,
no cloud project, and no ``anthropic`` SDK — a working Claude Code
subscription is the only requirement.

Three flags carry the design and should not be dropped:

* ``--safe-mode``  disables plugins, hooks, skills and CLAUDE.md for the
  child process. Without it the audit call re-triggers Forge Protocol's
  own hooks and recurses. Auth still resolves normally under safe mode.
  (``--bare`` looks like it would do the same job but forces API-key auth
  — it would reintroduce the dependency this transport exists to remove.)
* ``--tools ""``   the auditor is a judge, not an agent. No filesystem,
  no bash, no web.
* ``--json-schema`` server-side structured output, so the reply is parsed
  for us instead of scraped out of prose.

Configuration via environment variables:

    FORGE_AUDITOR_ENABLED   "0"/"false"/"no"/"off" to disable (default: enabled)
    FORGE_AUDITOR_MODEL     CLI model alias or id (default: sonnet)
    FORGE_AUDITOR_CMD       path to the claude binary (default: "claude")
    FORGE_AUDITOR_TIMEOUT   subprocess timeout in seconds (default: 60)

Use the same variables for canary scoring — the auditor is shared.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .validator import InputRules, OutputRules


DEFAULT_MODEL = "sonnet"
DEFAULT_CMD = "claude"
DEFAULT_TIMEOUT = 60

#: A runner takes (system_prompt, user_prompt, json_schema) and returns the
#: parsed JSON object the model produced. It raises on any failure; callers
#: convert that into a non-blocking ``error`` result. Tests inject one of
#: these instead of spawning a subprocess.
Runner = Callable[[str, str, dict], dict]

#: Marks the auditor's own child process so Forge's hooks no-op inside it.
#: Belt and braces alongside ``--safe-mode``.
CHILD_ENV_VAR = "FORGE_AUDITOR_CHILD"


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class RuleViolation:
    rule: str
    kind: str              # "required_missing" | "forbidden" | "input"
    quote: str = ""        # verbatim excerpt from the audited text, if any
    reason: str = ""       # one-line explanation


@dataclass
class AuditResult:
    compliant: bool
    violations: list[RuleViolation] = field(default_factory=list)
    auditor_model: str = ""
    raw_response: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "compliant": self.compliant,
            "violations": [
                {"rule": v.rule, "kind": v.kind, "quote": v.quote, "reason": v.reason}
                for v in self.violations
            ],
            "auditor_model": self.auditor_model,
            "error": self.error,
        }


@dataclass
class CanaryScore:
    overall: float
    dimensions: dict[str, int] = field(default_factory=dict)
    notes: str = ""
    auditor_model: str = ""
    error: str | None = None


# ---------------------------------------------------------------------------
# Response schemas (passed to --json-schema)
# ---------------------------------------------------------------------------

def _violations_schema(kinds: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "compliant": {"type": "boolean"},
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule": {"type": "string"},
                        "kind": {"type": "string", "enum": kinds},
                        "quote": {"type": "string"},
                        "reason": {"type": "string"},
                    },
                    "required": ["rule", "kind", "quote", "reason"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["compliant", "violations"],
        "additionalProperties": False,
    }


OUTPUT_AUDIT_SCHEMA = _violations_schema(["required_missing", "forbidden"])
INPUT_AUDIT_SCHEMA = _violations_schema(["input"])

CANARY_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "dimensions": {
            "type": "object",
            "properties": {
                "clarity": {"type": "integer", "minimum": 1, "maximum": 5},
                "depth": {"type": "integer", "minimum": 1, "maximum": 5},
                "independence": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["clarity", "depth", "independence"],
            "additionalProperties": False,
        },
        "notes": {"type": "string"},
    },
    "required": ["dimensions", "notes"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_OUTPUT_AUDIT_SYSTEM = (
    "You are an adversarial auditor for the Forge Protocol. Your job is to "
    "evaluate whether an AI response complied with the behavioral rules of a "
    "given interaction mode. Be strict. If a response is close-but-not-quite, "
    "flag it. Cite specific text. Do not rubber-stamp because the response "
    "sounds reasonable — judge only against the rules."
)

_OUTPUT_AUDIT_USER_TEMPLATE = """\
MODE: {mode_name} ({mode_id})

REQUIRED BEHAVIORS (the response must demonstrate all of these):
{required}

FORBIDDEN BEHAVIORS (the response must do NONE of these):
{forbidden}

RESPONSE TO AUDIT:
---
{response}
---

Rules for judgment:
- If a REQUIRED behavior is not clearly demonstrated, include it with kind="required_missing" and quote="".
- If a FORBIDDEN behavior is present, include it with kind="forbidden" and a verbatim quote.
- If fully compliant, return compliant=true with an empty violations array.
"""


_INPUT_AUDIT_SYSTEM = (
    "You are an adversarial auditor for the Forge Protocol. Evaluate whether a "
    "user's input meets the mode's entry requirements. In thinking modes, users "
    "must not fragment-dump or ask the AI to think for them. If the input is "
    "insufficient, flag which rule is unmet."
)

_INPUT_AUDIT_USER_TEMPLATE = """\
MODE: {mode_name} ({mode_id})

INPUT RULES (the user must satisfy all of these before the LLM engages):
{rules}

USER INPUT:
---
{user_input}
---

For every rule that is not met, add a violation with kind="input", quote="",
and a one-sentence reason explaining what is missing. If every rule is met,
return compliant=true with an empty violations array.
"""


_CANARY_SCORE_SYSTEM = (
    "You are a writing and reasoning evaluator. Score a user's unassisted "
    "response to a canary prompt on three dimensions (1-5 integers) and give "
    "one sentence of notes. Be honest — the user is using these scores to "
    "track whether their independent skills are improving or decaying over "
    "time, so flattery is counterproductive."
)

_CANARY_SCORE_USER_TEMPLATE = """\
CANARY PROMPT (the user was asked to answer this unassisted):
{prompt}

USER'S UNASSISTED RESPONSE:
---
{response}
---

Score the response on these dimensions, each 1 (poor) to 5 (excellent):
- clarity: specific, readable, no unnecessary hedging
- depth: shows genuine reasoning, not templated filler
- independence: reads like the user's own voice, not pasted AI output

Add one sentence of notes on the strongest or weakest aspect.
"""


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_FALSEY = ("0", "false", "no", "off")


def is_enabled() -> bool:
    """The auditor is on by default.

    It needs no API key and no paid extra any more, so the honest default is
    enabled. Set FORGE_AUDITOR_ENABLED=0 to fall back to orchestrator
    self-evaluation.
    """
    raw = os.environ.get("FORGE_AUDITOR_ENABLED")
    if raw is None or raw == "":
        return True
    return raw.strip().lower() not in _FALSEY


def model_name() -> str:
    return os.environ.get("FORGE_AUDITOR_MODEL") or DEFAULT_MODEL


def cli_path() -> str:
    return os.environ.get("FORGE_AUDITOR_CMD") or DEFAULT_CMD


def timeout_seconds() -> int:
    raw = os.environ.get("FORGE_AUDITOR_TIMEOUT")
    if not raw:
        return DEFAULT_TIMEOUT
    try:
        return max(1, int(raw))
    except ValueError:
        return DEFAULT_TIMEOUT


def is_available() -> bool:
    """True if the auditor is enabled and its transport can actually run."""
    if not is_enabled():
        return False
    if os.environ.get(CHILD_ENV_VAR):
        return False
    cmd = cli_path()
    return bool(shutil.which(cmd) or os.path.isfile(cmd))


# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------

def build_argv(system: str, schema: dict, user: str) -> list[str]:
    """Assemble the headless `claude -p` command line. Exposed for tests."""
    return [
        cli_path(),
        "-p",
        user,
        "--model", model_name(),
        "--system-prompt", system,
        "--json-schema", json.dumps(schema),
        "--output-format", "json",
        "--tools", "",
        "--safe-mode",
        "--no-session-persistence",
    ]


def _cli_runner(system: str, user: str, schema: dict) -> dict[str, Any]:
    """Run one audit through the Claude Code CLI and return the parsed object.

    Raises on any failure — callers turn that into a non-blocking result.
    """
    if os.environ.get(CHILD_ENV_VAR):
        raise RuntimeError("refusing to nest auditor calls")

    env = dict(os.environ)
    env[CHILD_ENV_VAR] = "1"

    proc = subprocess.run(
        build_argv(system, schema, user),
        capture_output=True,
        text=True,
        timeout=timeout_seconds(),
        env=env,
        check=False,
    )
    if proc.returncode != 0:
        # Deliberately does not carry stderr — see the note on `error` below.
        raise RuntimeError(f"claude exited {proc.returncode}")

    envelope = json.loads(proc.stdout)
    if envelope.get("is_error"):
        raise RuntimeError("claude reported is_error")

    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured

    # Fall back to the text result when structured output is unavailable.
    result = envelope.get("result")
    if isinstance(result, str) and result.strip():
        return json.loads(result)

    raise ValueError("no structured output in auditor response")


def _run(runner: Runner | None, system: str, user: str, schema: dict) -> dict[str, Any]:
    return (runner or _cli_runner)(system, user, schema)


def _fmt_bullets(items: list[str]) -> str:
    return "\n".join(f"- {s}" for s in items) if items else "(none)"


def _parse_violations(parsed: dict[str, Any], default_kind: str) -> list[RuleViolation]:
    raw = parsed.get("violations") or []
    if not isinstance(raw, list):
        return []
    return [
        RuleViolation(
            rule=str(v.get("rule", "")),
            kind=str(v.get("kind", default_kind)),
            quote=str(v.get("quote", "")),
            reason=str(v.get("reason", "")),
        )
        for v in raw
        if isinstance(v, dict)
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def audit_output(
    response: str,
    rules: "OutputRules",
    *,
    runner: Runner | None = None,
) -> AuditResult | None:
    """Audit a response against a mode's output rules.

    Returns None if the auditor is disabled (caller should fall back to
    self-evaluation). Returns an AuditResult with ``error`` populated on
    transport/parse failure — by convention, audit errors do not block the
    response (``compliant`` defaults to True on error).
    """
    if not is_enabled():
        return None

    model = model_name()
    try:
        user = _OUTPUT_AUDIT_USER_TEMPLATE.format(
            mode_name=rules.mode_name,
            mode_id=rules.mode,
            required=_fmt_bullets(rules.required_behaviors),
            forbidden=_fmt_bullets(rules.forbidden_behaviors),
            response=response,
        )
        parsed = _run(runner, _OUTPUT_AUDIT_SYSTEM, user, OUTPUT_AUDIT_SCHEMA)
        return AuditResult(
            compliant=bool(parsed.get("compliant", True)),
            violations=_parse_violations(parsed, "forbidden"),
            auditor_model=model,
            raw_response=json.dumps(parsed),
        )
    except Exception as e:  # noqa: BLE001 — auditor must never crash the caller
        return AuditResult(
            compliant=True,
            violations=[],
            auditor_model=model,
            raw_response="",
            error=type(e).__name__,
        )


def audit_input(
    user_input: str,
    rules: "InputRules",
    *,
    runner: Runner | None = None,
) -> AuditResult | None:
    """Audit a user input against a mode's input rules."""
    if not is_enabled():
        return None
    if not rules.rules:
        # nothing to check (executor mode, etc.)
        return AuditResult(compliant=True, auditor_model=model_name())

    model = model_name()
    try:
        user = _INPUT_AUDIT_USER_TEMPLATE.format(
            mode_name=rules.mode_name,
            mode_id=rules.mode,
            rules=_fmt_bullets(rules.rules),
            user_input=user_input,
        )
        parsed = _run(runner, _INPUT_AUDIT_SYSTEM, user, INPUT_AUDIT_SCHEMA)
        violations = _parse_violations(parsed, "input")
        for v in violations:
            v.kind = "input"
        return AuditResult(
            compliant=bool(parsed.get("compliant", True)),
            violations=violations,
            auditor_model=model,
            raw_response=json.dumps(parsed),
        )
    except Exception as e:  # noqa: BLE001
        return AuditResult(
            compliant=True,
            violations=[],
            auditor_model=model,
            raw_response="",
            error=type(e).__name__,
        )


def score_canary(
    prompt: str,
    response: str,
    *,
    runner: Runner | None = None,
) -> CanaryScore:
    """Score a user's unassisted canary response on clarity, depth, independence.

    Unlike ``audit_*``, this returns a score even when the auditor is disabled
    — in that case the returned CanaryScore has overall=0 and ``error`` set,
    so callers can still store the raw response for future scoring.
    """
    if not is_enabled():
        return CanaryScore(
            overall=0.0,
            dimensions={},
            notes="",
            auditor_model="",
            error="auditor_disabled",
        )

    model = model_name()
    try:
        user = _CANARY_SCORE_USER_TEMPLATE.format(prompt=prompt, response=response)
        parsed = _run(runner, _CANARY_SCORE_SYSTEM, user, CANARY_SCORE_SCHEMA)
        dims = {k: int(v) for k, v in (parsed.get("dimensions") or {}).items()}
        overall = sum(dims.values()) / len(dims) if dims else 0.0
        return CanaryScore(
            overall=round(overall, 2),
            dimensions=dims,
            notes=str(parsed.get("notes", "")),
            auditor_model=model,
        )
    except Exception as e:  # noqa: BLE001
        return CanaryScore(
            overall=0.0,
            dimensions={},
            notes="",
            auditor_model=model,
            error=type(e).__name__,
        )

"""Hook stdin/stdout plumbing and output builders.

The host invokes a hook as a shell command, hands it a JSON payload on
stdin, and reads a JSON object back from stdout. The helpers here build the
exact output shapes for the events this plugin uses, so the handlers stay
about policy rather than wire format.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def read_payload(stream: Any = None) -> dict[str, Any]:
    """Parse the hook payload from stdin. A malformed payload yields {}."""
    stream = stream or sys.stdin
    try:
        raw = stream.read()
    except OSError:
        return {}
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def emit(output: dict[str, Any] | None, stream: Any = None) -> None:
    """Write a hook result. An empty result prints nothing at all."""
    stream = stream or sys.stdout
    if not output:
        return
    json.dump(output, stream)
    stream.write("\n")


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------

def additional_context(event: str, context: str) -> dict[str, Any]:
    """Inject text into the model's context for the coming turn."""
    return {
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }


def deny_tool(reason: str) -> dict[str, Any]:
    """Refuse a tool call outright, telling the model why."""
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def block(reason: str) -> dict[str, Any]:
    """Block the current step and hand the reason back to the model.

    On UserPromptSubmit this stops the prompt; on Stop it sends the agent
    back for another turn.
    """
    return {"decision": "block", "reason": reason}


def notify(message: str) -> dict[str, Any]:
    """Surface a message to the user without steering the model."""
    return {"systemMessage": message}


def _decision_of(output: dict[str, Any] | None) -> str:
    """One word for what a hook did, for the trace log."""
    if not output:
        return "pass"
    if output.get("decision"):
        return str(output["decision"])
    specific = output.get("hookSpecificOutput")
    if isinstance(specific, dict):
        if specific.get("permissionDecision"):
            return str(specific["permissionDecision"])
        if specific.get("additionalContext"):
            return "context"
    if output.get("systemMessage"):
        return "notify"
    return "pass"


def _trace(
    handler: Any,
    payload: dict[str, Any],
    output: dict[str, Any] | None,
    error: str | None,
    started: float,
) -> None:
    """Append one line describing this hook run, if tracing is on.

    Hooks are silent by design, and their stderr is invisible from inside a
    running interactive session — so FORGE_HOOK_TRACE=1 writes a JSONL trail
    you can `tail -f` from another terminal while you drive the host.
    Never raises: a broken trace must not break a hook.
    """
    import os

    if not os.environ.get("FORGE_HOOK_TRACE"):
        return
    try:
        import json as _json
        import time
        from pathlib import Path

        state = os.environ.get("FORGE_STATE_DIR")
        base = Path(state).expanduser() if state else Path.home() / ".forge-state"
        target = base / "audit" / "hooks.jsonl"
        target.parent.mkdir(parents=True, exist_ok=True)

        record = {
            "ts": round(time.time(), 3),
            "hook": getattr(handler, "__name__", "?"),
            "session_id": payload.get("session_id"),
            "tool": payload.get("tool_name"),
            "prompt_chars": len(payload.get("prompt") or "") or None,
            "stop_hook_active": payload.get("stop_hook_active"),
            "decision": _decision_of(output),
            "reason_chars": len(str(output.get("reason", ""))) or None if output else None,
            "ms": int((time.time() - started) * 1000),
            "error": error,
        }
        with open(target, "a", encoding="utf-8") as f:
            f.write(_json.dumps({k: v for k, v in record.items() if v is not None}) + "\n")
    except Exception:  # noqa: BLE001 — tracing is never worth a failed hook
        pass


def run(handler: Any) -> int:
    """Drive one hook end to end, and never let it break the session.

    A crashed hook is worse than a skipped one: the Forge Protocol is a
    guardrail, not a gate on the user getting their work done. Any exception
    is swallowed and the hook exits 0 with no output, so the host proceeds
    exactly as if the plugin were not installed. Set FORGE_HOOK_DEBUG=1 to see
    the traceback on stderr, or FORGE_HOOK_TRACE=1 for a tailable JSONL trail.
    """
    import os
    import time

    started = time.time()
    payload: dict[str, Any] = {}
    output: dict[str, Any] | None = None
    error: str | None = None

    try:
        payload = read_payload()
        output = handler(payload)
        emit(output)
    except BaseException as exc:  # noqa: BLE001 — a hook must not take the session down
        error = type(exc).__name__
        if os.environ.get("FORGE_HOOK_DEBUG"):
            import traceback

            traceback.print_exc(file=sys.stderr)

    _trace(handler, payload, output, error, started)
    return 0


def merge(*outputs: dict[str, Any] | None) -> dict[str, Any]:
    """Combine hook outputs, concatenating any additionalContext blocks."""
    merged: dict[str, Any] = {}
    contexts: list[str] = []
    event = ""

    for out in outputs:
        if not out:
            continue
        specific = out.get("hookSpecificOutput")
        if isinstance(specific, dict) and "additionalContext" in specific:
            event = specific.get("hookEventName", event)
            contexts.append(str(specific["additionalContext"]))
            rest = {k: v for k, v in out.items() if k != "hookSpecificOutput"}
            merged.update(rest)
        else:
            merged.update(out)

    if contexts:
        merged["hookSpecificOutput"] = {
            "hookEventName": event,
            "additionalContext": "\n\n".join(c for c in contexts if c),
        }
    return merged

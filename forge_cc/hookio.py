"""Hook stdin/stdout plumbing and output builders.

Claude Code invokes a hook as a shell command, hands it a JSON payload on
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


def run(handler: Any) -> int:
    """Drive one hook end to end, and never let it break the session.

    A crashed hook is worse than a skipped one: the Forge Protocol is a
    guardrail, not a gate on the user getting their work done. Any exception
    is swallowed and the hook exits 0 with no output, so Claude Code proceeds
    exactly as if the plugin were not installed. Set FORGE_HOOK_DEBUG=1 to see
    the traceback on stderr.
    """
    import os

    try:
        emit(handler(read_payload()))
    except BaseException:  # noqa: BLE001 — a hook must not take the session down
        if os.environ.get("FORGE_HOOK_DEBUG"):
            import traceback

            traceback.print_exc(file=sys.stderr)
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

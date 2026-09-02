"""Read the agent's own words back out of a Claude Code transcript.

The Stop hook needs the response it is about to audit. Claude Code hands the
hook a `transcript_path` pointing at the session's JSONL log rather than the
text itself, so we read the last assistant message out of it.

Everything here is deliberately defensive: an unreadable or unfamiliar
transcript returns an empty string, which callers treat as "nothing to audit"
rather than as an error. The auditor must never block a response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

#: Content block types that are not part of the user-visible response.
_SKIP_BLOCKS = {"thinking", "redacted_thinking", "tool_use", "tool_result"}


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") in _SKIP_BLOCKS:
            continue
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _has_role(entry: dict[str, Any], role: str) -> bool:
    if entry.get("type") == role:
        return True
    message = entry.get("message")
    return isinstance(message, dict) and message.get("role") == role


def _is_assistant(entry: dict[str, Any]) -> bool:
    return _has_role(entry, "assistant")


def _last_text_for(transcript_path: str | Path | None, role: str) -> str:
    """Most recent message from `role` that carried visible text."""
    if not transcript_path:
        return ""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return ""

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or not _has_role(entry, role):
            continue

        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else entry.get("content")
        text = _text_from_content(content)
        if text:
            return text

    return ""


def last_user_text(transcript_path: str | Path | None) -> str:
    """The message the audited response was replying to.

    The auditor needs it to judge proportionality: a mode's full apparatus is
    the right answer to a real problem and the wrong answer to "yes".
    """
    return _last_text_for(transcript_path, "user")


def _entries(transcript_path: str | Path | None) -> list[dict[str, Any]]:
    if not transcript_path:
        return []
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    out: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def _text_of(entry: dict[str, Any]) -> str:
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else entry.get("content")
    return _text_from_content(content)


def _assistant_text_after_last_user(entries: list[dict[str, Any]]) -> str:
    anchor = -1
    for index, entry in enumerate(entries):
        # tool_result entries also carry role "user"; _text_of skips those
        # blocks, so a real prompt is a user entry with visible text.
        if _has_role(entry, "user") and _text_of(entry):
            anchor = index

    parts = [
        text
        for entry in entries[anchor + 1 :]
        if _has_role(entry, "assistant") and (text := _text_of(entry))
    ]
    return "\n\n".join(parts)


def assistant_text_after_last_user(transcript_path: str | Path | None) -> str:
    """Assistant text written *after* the last real user message.

    Anchoring on the user's turn is what keeps the auditor honest. Reading the
    newest assistant message unconditionally is not equivalent: when the Stop
    hook fires before Claude Code has flushed the response to disk, the newest
    assistant text on disk belongs to the *previous* turn — so the auditor
    judges a response the user never saw blocked and the model is told to
    revise something that was never checked. Observed in the wild; the audit
    quoted a mode-switch banner from two turns earlier.

    Returns "" when no assistant text follows the last user message, which
    callers treat as "nothing to audit" rather than as an error.
    """
    return _assistant_text_after_last_user(_entries(transcript_path))


def response_under_audit(
    transcript_path: str | Path | None,
    *,
    timeout: float | None = None,
) -> str:
    """The response the Stop hook should audit, waiting briefly for the flush.

    The write and the hook race. Skipping the audit whenever the transcript is
    behind would quietly disable the auditor; auditing stale text is worse. So
    poll for a short while, then give up and audit nothing.
    """
    import os
    import time

    if timeout is None:
        raw = os.environ.get("FORGE_TRANSCRIPT_WAIT")
        try:
            timeout = float(raw) if raw else 2.0
        except ValueError:
            timeout = 2.0

    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        entries = _entries(transcript_path)
        text = _assistant_text_after_last_user(entries)
        if text:
            return text

        # Only the actual race is worth waiting on: we can see the user's turn
        # but not the reply yet. An absent, empty, or user-less transcript will
        # not grow a reply in the next two seconds, so don't stall the hook.
        pending = any(_has_role(e, "user") and _text_of(e) for e in entries)
        if not pending or time.monotonic() >= deadline:
            return ""
        time.sleep(0.05)


def last_assistant_text(transcript_path: str | Path | None) -> str:
    """Return the most recent assistant message that carried visible text."""
    if not transcript_path:
        return ""
    path = Path(transcript_path).expanduser()
    if not path.is_file():
        return ""

    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""

    for line in reversed(lines):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or not _is_assistant(entry):
            continue

        message = entry.get("message")
        content = message.get("content") if isinstance(message, dict) else entry.get("content")
        text = _text_from_content(content)
        if text:
            return text

    return ""

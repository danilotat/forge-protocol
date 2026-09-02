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


def _is_assistant(entry: dict[str, Any]) -> bool:
    if entry.get("type") == "assistant":
        return True
    message = entry.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


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

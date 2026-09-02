"""Tests for reading the last assistant message out of a Claude Code transcript.

The Stop hook is handed a `transcript_path`, not the text it needs to audit,
so `last_assistant_text` digs the response out of a JSONL log. Two properties
matter: it must find the *visible* text (skipping thinking and tool blocks,
walking back past tool-only turns), and it must degrade to "" — never raise —
on anything it does not recognize. An unreadable transcript means "nothing to
audit", and the auditor is never allowed to break a session.
"""
from __future__ import annotations

import json

from forge_cc.transcript import last_assistant_text


def _write(path, entries) -> str:
    path.write_text(
        "\n".join(json.dumps(e) if not isinstance(e, str) else e for e in entries),
        encoding="utf-8",
    )
    return str(path)


def _assistant(*blocks):
    return {"type": "assistant", "message": {"role": "assistant", "content": list(blocks)}}


def _user(text):
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def _text(text):
    return {"type": "text", "text": text}


# ---------------------------------------------------------------------------
# Finding the response
# ---------------------------------------------------------------------------

def test_returns_the_last_assistant_text(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_text("first answer")),
        _user("and then?"),
        _assistant(_text("second answer")),
    ])
    assert last_assistant_text(path) == "second answer"


def test_ignores_user_entries(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_text("the answer")),
        _user("thanks, but what about X?"),
    ])
    assert last_assistant_text(path) == "the answer"


def test_skips_thinking_and_tool_blocks(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(
            {"type": "thinking", "thinking": "the user wants me to write it for them"},
            {"type": "redacted_thinking", "data": "opaque"},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {}},
            {"type": "tool_result", "tool_use_id": "t1", "content": "file contents"},
            _text("What's your own take on this?"),
        ),
    ])
    result = last_assistant_text(path)
    assert result == "What's your own take on this?"
    assert "thinking" not in result
    assert "file contents" not in result


def test_joins_multiple_text_blocks(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_text("first paragraph"), _text("second paragraph")),
    ])
    assert last_assistant_text(path) == "first paragraph\n\nsecond paragraph"


def test_handles_plain_string_content(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        {"type": "assistant", "message": {"role": "assistant", "content": "  a plain string  "}},
    ])
    assert last_assistant_text(path) == "a plain string"


def test_handles_content_at_the_top_level(tmp_path):
    """Some transcript shapes put content on the entry rather than in message."""
    path = _write(tmp_path / "t.jsonl", [
        {"type": "assistant", "content": [_text("top-level content")]},
    ])
    assert last_assistant_text(path) == "top-level content"


def test_recognizes_an_assistant_by_message_role(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        {"message": {"role": "assistant", "content": [_text("role-tagged only")]}},
    ])
    assert last_assistant_text(path) == "role-tagged only"


def test_walks_back_past_a_tool_only_turn(tmp_path):
    """The final assistant turn is often just a tool call with no prose."""
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_text("Which constraint is actually binding here?")),
        _assistant({"type": "tool_use", "id": "t2", "name": "Grep", "input": {}}),
        _assistant({"type": "tool_result", "tool_use_id": "t2", "content": "3 matches"}),
    ])
    assert last_assistant_text(path) == "Which constraint is actually binding here?"


def test_walks_back_past_whitespace_only_text(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant(_text("real content")),
        _assistant(_text("   \n  ")),
    ])
    assert last_assistant_text(path) == "real content"


def test_skips_blank_lines_and_keeps_reading(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(_assistant(_text("survived the blanks"))) + "\n\n\n",
        encoding="utf-8",
    )
    assert last_assistant_text(str(path)) == "survived the blanks"


def test_accepts_a_path_object(tmp_path):
    path = tmp_path / "t.jsonl"
    _write(path, [_assistant(_text("path object works"))])
    assert last_assistant_text(path) == "path object works"


# ---------------------------------------------------------------------------
# Degradation — every one of these means "nothing to audit"
# ---------------------------------------------------------------------------

def test_none_returns_empty():
    assert last_assistant_text(None) == ""


def test_empty_string_path_returns_empty():
    assert last_assistant_text("") == ""


def test_missing_file_returns_empty(tmp_path):
    assert last_assistant_text(str(tmp_path / "does-not-exist.jsonl")) == ""


def test_directory_returns_empty(tmp_path):
    assert last_assistant_text(str(tmp_path)) == ""


def test_empty_file_returns_empty(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("", encoding="utf-8")
    assert last_assistant_text(str(path)) == ""


def test_malformed_json_lines_return_empty(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("not json\n{oops\n[1, 2,\n", encoding="utf-8")
    assert last_assistant_text(str(path)) == ""


def test_malformed_lines_do_not_hide_a_good_one(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(
        json.dumps(_assistant(_text("good line"))) + "\n{ broken\nalso broken\n",
        encoding="utf-8",
    )
    assert last_assistant_text(str(path)) == "good line"


def test_non_object_json_lines_return_empty(tmp_path):
    path = _write(tmp_path / "t.jsonl", ["[1, 2, 3]", '"a bare string"', "42"])
    assert last_assistant_text(path) == ""


def test_no_assistant_entries_returns_empty(tmp_path):
    path = _write(tmp_path / "t.jsonl", [_user("hello"), _user("anyone there?")])
    assert last_assistant_text(path) == ""


def test_assistant_with_only_tool_blocks_returns_empty(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        _assistant({"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}),
    ])
    assert last_assistant_text(path) == ""


def test_unexpected_content_types_return_empty(tmp_path):
    path = _write(tmp_path / "t.jsonl", [
        {"type": "assistant", "message": {"role": "assistant", "content": 17}},
        {"type": "assistant", "message": {"role": "assistant", "content": [None, 5, "str"]}},
    ])
    assert last_assistant_text(path) == ""


# ---------------------------------------------------------------------------
# Anchoring the audit on the user's turn
#
# Regression tests for a real misfire: the Stop hook raced the transcript
# write, read the newest assistant text on disk — which belonged to the
# PREVIOUS turn — and blocked a response nobody had judged, quoting a
# mode-switch banner from two turns earlier.
# ---------------------------------------------------------------------------

def _jsonl(path, entries):
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _u(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def _a(text):
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]},
    }


def test_returns_nothing_when_the_transcript_is_behind(tmp_path):
    """The exact race. Auditing nothing beats auditing the wrong turn."""
    from forge_cc.transcript import assistant_text_after_last_user

    path = tmp_path / "t.jsonl"
    _jsonl(path, [
        _a("Forge mode. I won't write for you here."),  # previous turn
        _u("I was testing whether the lock holds"),          # new prompt
        # the new response has not been flushed yet
    ])
    assert assistant_text_after_last_user(path) == ""


def test_returns_only_text_after_the_last_user_message(tmp_path):
    from forge_cc.transcript import assistant_text_after_last_user

    path = tmp_path / "t.jsonl"
    _jsonl(path, [
        _a("stale banner from the previous turn"),
        _u("the new prompt"),
        _a("the reply that should be audited"),
    ])
    got = assistant_text_after_last_user(path)
    assert got == "the reply that should be audited"
    assert "stale" not in got


def test_joins_multiple_assistant_entries_in_one_turn(tmp_path):
    """A turn split across entries must be audited whole, in order."""
    from forge_cc.transcript import assistant_text_after_last_user

    path = tmp_path / "t.jsonl"
    _jsonl(path, [
        _u("prompt"),
        _a("first part"),
        {"type": "assistant", "message": {"role": "assistant",
                                          "content": [{"type": "tool_use", "id": "x"}]}},
        _a("second part"),
    ])
    assert assistant_text_after_last_user(path) == "first part\n\nsecond part"


def test_tool_results_do_not_count_as_the_user_anchor(tmp_path):
    """tool_result entries carry role user; they must not reset the anchor."""
    from forge_cc.transcript import assistant_text_after_last_user

    path = tmp_path / "t.jsonl"
    _jsonl(path, [
        _u("the real prompt"),
        _a("before the tool call"),
        {"type": "user", "message": {"role": "user",
                                     "content": [{"type": "tool_result", "content": "ok"}]}},
        _a("after the tool call"),
    ])
    got = assistant_text_after_last_user(path)
    assert got == "before the tool call\n\nafter the tool call"


def test_response_under_audit_gives_up_rather_than_hanging(tmp_path):
    from forge_cc.transcript import response_under_audit

    path = tmp_path / "t.jsonl"
    _jsonl(path, [_a("stale"), _u("prompt")])
    assert response_under_audit(path, timeout=0) == ""


def test_response_under_audit_returns_the_fresh_reply(tmp_path):
    from forge_cc.transcript import response_under_audit

    path = tmp_path / "t.jsonl"
    _jsonl(path, [_u("prompt"), _a("fresh reply")])
    assert response_under_audit(path, timeout=0) == "fresh reply"


def test_stop_hook_does_not_block_on_a_stale_transcript(tmp_path, monkeypatch):
    """End to end: the race must not produce a block."""
    from forge_cc import handlers

    monkeypatch.setenv("FORGE_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FORGE_TRANSCRIPT_WAIT", "0")

    def never_called(*_a, **_k):
        raise AssertionError("the auditor must not run on a stale transcript")

    monkeypatch.setattr("lib.auditor.audit_output", never_called)

    path = tmp_path / "t.jsonl"
    _jsonl(path, [_a("previous turn"), _u("new prompt")])

    from forge_cc.cli import main as cli_main
    cli_main(["set-mode", "forge", "--session-id", "st1"])

    out = handlers.stop({
        "session_id": "st1", "cwd": str(tmp_path),
        "transcript_path": str(path), "stop_hook_active": False,
    })
    assert out == {}

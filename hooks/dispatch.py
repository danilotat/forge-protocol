#!/usr/bin/env python3
"""Dispatch every Forge lifecycle event through one hook entry point."""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from forge_cc import handlers, hookio  # noqa: E402


HANDLERS = {
    "pre-tool-use": handlers.pre_tool_use,
    "session-end": handlers.session_end,
    "session-start": handlers.session_start,
    "stop": handlers.stop,
    "subagent-stop": handlers.subagent_stop,
    "user-prompt-submit": handlers.user_prompt_submit,
}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    handler = HANDLERS.get(args[0] if args else "")
    if handler is None:
        return 0
    return hookio.run(handler)


if __name__ == "__main__":
    raise SystemExit(main())

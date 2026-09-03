"""Codex and Claude Code integration layer for the Forge Protocol.

This is the only host-aware Python in the repo. `lib/` stays a pure,
portable core with zero host dependency; the prompt layer lives in `modes/`,
`souls/`, `agents/` and `skills/`. Everything that knows about hook payloads,
plugin paths, or external auditor transport belongs here.
"""

__all__ = ["cli", "handlers", "hookio", "paths", "transcript"]

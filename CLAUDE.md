# Repository guide

Forge Protocol is one plugin for both Codex and Claude Code. Keep the shared
implementation small; host-specific behavior belongs only at the manifest or
payload-normalization boundary.

The mode design is evidence-backed. Treat the citations and behavioral mapping
in `RESEARCH.md`, `souls/`, `modes/` and `agents/` as functional constraints.

## Verify changes

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev python scripts/build_modes_json.py --check
python3 scripts/verify_enforcement.py
claude plugin validate --strict .
```

Tests must not make network or model calls. Inject an auditor runner or put a
fake `claude` executable on `PATH`. Use a temporary `FORGE_STATE_DIR` when
manually exercising stateful commands.

## Architecture

- `lib/` is the host-independent core. It has no runtime dependencies and must
  not import `forge_cc` or host APIs.
- `forge_cc/` is the adapter, hook policy and CLI. The legacy name is retained
  for import and installation compatibility; it supports both hosts.
- `hooks/hooks.json` and `hooks/dispatch.py` are the only hook wiring.
- `skills/`, `agents/`, `souls/` and `modes/` are the prompt and policy layer.
- `.codex-plugin/plugin.json` and `.claude-plugin/plugin.json` are thin host
  manifests. `.claude-plugin/marketplace.json` is the shared catalog.

## Invariants

- Hooks never crash or block a session because of an internal error.
- The external auditor runs through `claude -p`, never an API key or SDK, and
  fails open when unavailable.
- The thinking-mode write lock fails closed and cannot be bypassed through the
  auditor-child flag or a CLI mode change.
- Mode relaxation requires an explicit user invocation. Accept `$mode-name` in
  Codex, `/mode-name` in Claude Code, and Claude's namespaced command wrapper;
  never treat a prose mention as consent.
- Codex output auditing reads `last_assistant_message`. Claude Code falls back
  to its transcript, anchored after the latest user message so stale output is
  never audited.
- Executor performs no per-turn audit, write lock or checkpoint work.
- Auditor errors expose only an exception type, never stderr or secrets.
- Stop-hook revisions are bounded by `FORGE_MAX_REVISIONS`.
- The shell write detector remains a narrow guardrail, not a shell parser.
- A hook's `additionalContext` stays under `HOST_CONTEXT_BUDGET`. Past roughly
  10 KiB Claude Code replaces the whole payload with a 2 KB preview and still
  exits 0, so an oversized soul drops the routing contract silently. The mode
  souls are the bulk; keep `souls/forge-orchestrator.md` lean.

## Mode definitions

YAML is the source of truth. After editing `modes/*.yaml`, regenerate and commit
the JSON twin:

```bash
uv run --extra dev python scripts/build_modes_json.py
```

For a new first-class mode, update the mode YAML and soul, `VALID_MODE_IDS`,
dependency-report ratios, hook thinking-mode and invocation maps, plus its skill
and optional agent. Keep machine-readable rules and generation prompts aligned.

`behaviors.required` applies to every response. Put cadence- or trigger-based
rules in `behaviors.conditional`, with the trigger in the rule text.

## State and CLI

State lives under `FORGE_STATE_DIR` or `~/.forge-state`. Session IDs and soul
paths are traversal-guarded. `SessionStart` records the current session by
working directory because the CLI does not receive a host session ID.

CLI reads (`state`, `rules`, `checkpoint`, `report`, `canary trend`) must remain
side-effect free. Mutations must be explicit. `--force` is for a human at a TTY
and logs a forced-relaxation violation.

## Conventions

- Python 3.11+, type hints and `from __future__ import annotations`.
- No runtime package dependencies.
- Commit messages follow `type(scope): summary` when a scope helps.

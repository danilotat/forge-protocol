# Forge Protocol

Forge Protocol adds deliberate friction when an AI task should exercise human
judgment instead of replacing it. The same plugin runs on **Codex** and
**Claude Code** from one implementation.

It provides four modes:

| Mode | Purpose | Constraint |
| --- | --- | --- |
| Forge | Think through a decision | Asks questions; does not produce the answer |
| Anvil | Critique a draft | Evaluates; does not rewrite |
| Crucible | Stress-test ideas | Challenges ideas the user supplies |
| Executor | Complete mechanical work | Normal tool use, without cognitive friction |

The behavioral design and its research basis come from Lorenzo Famiglini's
[original Forge Protocol](https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent).
See [RESEARCH.md](RESEARCH.md) for the mapping between modes and evidence.

## Install

Requirements:

- Codex or Claude Code
- Python 3.11+ available as `python3`
- Git credentials able to clone this repository

### Codex

```text
codex plugin marketplace add danilotat/forge-protocol
codex plugin add forge-protocol@forge-protocol
```

Invoke skills with `$`:

```text
$forge-mode
$anvil-mode
$crucible-mode
$executor-mode
$forge-status
$forge-audit weekly
```

### Claude Code

From inside Claude Code:

```text
/plugin marketplace add danilotat/forge-protocol
/plugin install forge-protocol
```

Invoke skills with `/`:

```text
/forge-mode
/anvil-mode
/crucible-mode
/executor-mode
/forge-status
/forge-audit weekly
```

To try a clone without installing it:

```bash
claude --plugin-dir .
```

## What is enforced

The prompt layer explains each mode. Hooks provide deterministic guardrails:

- `UserPromptSubmit` applies explicit mode changes, counts messages and checks
  entry requirements.
- `PreToolUse` denies file-writing tools and obvious shell writes in Forge,
  Anvil and Crucible.
- `Stop` and `SubagentStop` inspect the completed response.
- `SessionStart` restores state and injects the active mode.
- `SessionEnd` emits the closing reflection for the active mode.

Codex and Claude Code load the same [hook configuration](hooks/hooks.json) and
the same Python dispatcher. Codex's `apply_patch` tool is normalized to the
write-tool policy used by Claude Code.

The optional independent auditor uses `claude -p` and the user's existing
Claude credentials; it needs no API key or SDK. When that command is disabled
or unavailable—for example on a Codex-only machine—the plugin degrades safely:
the deterministic write lock, mode state, checkpoints and prompt-level
self-evaluation still work, while external output auditing is skipped.

## Structure

```text
.codex-plugin/plugin.json       Codex manifest
.claude-plugin/plugin.json      Claude Code manifest
.claude-plugin/marketplace.json shared marketplace catalog
skills/                         user-facing modes and reports
hooks/hooks.json                shared lifecycle wiring
hooks/dispatch.py               single hook entry point
forge_cc/                       host adapter and CLI (legacy package name)
lib/                            host-independent policy and state
modes/ + souls/                 rules and system prompts
agents/                         optional delegated mode agents
```

`lib/` has no runtime dependencies and no knowledge of either host. The
historical package name `forge_cc` remains to preserve imports and installed
scripts; it now adapts both hosts.

Mode definitions are authored as YAML. Committed JSON twins let hooks run under
a bare Python installation without PyYAML. Never edit the JSON twins manually.

## Development

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev python scripts/build_modes_json.py --check
python3 scripts/verify_enforcement.py
claude plugin validate --strict .
```

Validate the Codex manifest with the validator from the Codex plugin-creator
skill when that development skill is installed.

Useful local commands:

```bash
./bin/forge doctor
FORGE_STATE_DIR=$(mktemp -d) ./bin/forge state
```

The hook process has no required third-party packages. Development dependencies
are optional and declared in `pyproject.toml`.

## Configuration

All settings are optional environment variables:

| Variable | Default | Effect |
| --- | --- | --- |
| `FORGE_STATE_DIR` | `~/.forge-state` | State and audit history location |
| `FORGE_AUDITOR_ENABLED` | `1` | Enables the external `claude -p` auditor |
| `FORGE_AUDITOR_MODEL` | `sonnet` | Auditor model |
| `FORGE_AUDITOR_ASYNC` | `1` | Defers output findings to the next turn |
| `FORGE_OUTPUT_BLOCK` | `0` | Requests an in-turn revision for a violation |
| `FORGE_HOOK_DEBUG` | `0` | Prints swallowed hook exceptions |
| `FORGE_HOOK_TRACE` | `0` | Writes hook decision traces under the state dir |

The auditor is deliberately fail-open so it cannot break an editor session.
The thinking-mode write lock is fail-closed: a missing mode definition does not
silently unlock writes.

## License and attribution

MIT. The protocol design, mode names, souls, canary system and research mapping
are derived from Lorenzo Famiglini's original project. This dual-host plugin is
maintained by [danilotat](https://github.com/danilotat).

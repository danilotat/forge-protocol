# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Forge Protocol is a **native Claude Code plugin** that enforces four interaction modes (Forge / Anvil / Crucible /
Executor) designed to prevent AI-induced deskilling. It began as a plugin for
[Hermes Agent](https://github.com/NousResearch/hermes-agent); that layer is gone, replaced by Claude Code hooks,
subagents, and skills.

The four modes map one-to-one onto empirically validated protocols from the Cabitza lab — see `RESEARCH.md`. When
changing mode behavior, preserve that mapping: the citations in `souls/*.md`, `souls/forge-orchestrator.md`, and
`agents/*.md` are load-bearing design rationale, not decoration.

**No API key.** The adversarial auditor shells out to `claude -p`, reusing the credentials Claude Code already has.
`ANTHROPIC_API_KEY`, `VERTEX_PROJECT`, and the `anthropic` SDK must never reappear.

## Commands

```bash
python3 -m pytest                      # run all tests — NOTE: bare `pytest` fails collection
FORGE_STATE_DIR=$(mktemp -d) python3 -m pytest    # how to actually run them (see gotchas)
python3 -m pytest tests/test_mode_guard.py -q     # single file

python3 scripts/verify_enforcement.py         # end-to-end: spawns the real hook shims, 50 checks
python3 scripts/verify_enforcement.py --live  # + one real auditor call (~8s, no API key)

python3 scripts/build_modes_json.py           # regenerate modes/*.json after editing a mode YAML
python3 scripts/build_modes_json.py --check   # CI: fail if a twin is stale

claude --plugin-dir .                  # load the plugin for one session, no install
claude plugin validate --strict .      # lint manifest + agents + skills (CI)
./bin/forge doctor                     # resolved paths, loaded modes, auditor state
```

**Test gotchas:**
- Bare `pytest` fails at collection unless the package is installed editable — the repo root isn't on `sys.path`
  otherwise. Use `python3 -m pytest`.
- Always run with `FORGE_STATE_DIR=$(mktemp -d)`. `tests/test_cli.py` and `tests/test_handlers.py` drive the real
  handlers and CLI, which write to the state dir.
- No test may make a network or model call. The auditor's seam is an injectable `runner` callable, or a fake `claude`
  executable on `PATH` (`tests/test_auditor_transport.py`).
- `claude plugin validate` targets the **marketplace** manifest when both live in `.claude-plugin/`. To lint
  `plugin.json` itself, point it at a directory containing only that file.

## Architecture

Four layers, deliberately separated:

1. **`lib/`** — pure Python core. **Zero host dependency and zero runtime dependencies.** This is a hard constraint:
   it must stay importable from any project. Never import `forge_cc/`, Claude Code, or anything about hooks from here.
2. **`forge_cc/`** — the only Claude-Code-aware Python. `handlers.py` (hook policy), `cli.py` (the `forge` CLI),
   `hookio.py` (stdin/stdout wire format), `paths.py` (plugin root, state dir, session pointer, mode-change consent),
   `transcript.py` (reading the agent's last message back out of a session log).
3. **`modes/*.yaml` + `souls/*.md` + `agents/*.md` + `skills/*/SKILL.md`** — the prompt layer. Modes define
   machine-readable rules, souls are the system prompts injected per mode, agents are delegable subagents, skills are
   the slash commands.
4. **Wiring** — `.claude-plugin/plugin.json` + `marketplace.json`, `hooks/hooks.json`, `hooks-handlers/*.py` (thin
   shims), `bin/forge`. Components are auto-discovered by convention; the manifest declares none of them, and has no
   field for environment variables.

### Enforcement is LLM-native, never regex

`lib/validator.py` does *not* validate anything — it returns the mode's natural-language rules so an LLM can judge
compliance. Both enforcement paths must keep working:

- **Auditor enabled (default):** an independent `claude -p` call judges compliance; the `Stop` hook blocks with the
  violation list.
- **Auditor disabled** (`FORGE_AUDITOR_ENABLED=0`): `lib.auditor.audit_*` returns `None` and the hook injects the bare
  rules for the model to self-evaluate.

**The write-lock fails closed.** `pre_tool_use` denies on the session's `current_mode` alone, so a modes/ directory
that will not load does not unlock writes; it is deliberately NOT guarded by `_suppressed()` (that guard is for
auditor recursion, and honouring `FORGE_AUDITOR_CHILD` there let one env var disable the lock); and it denies any
Bash command matching `_switches_mode`, because `Bash(forge set-mode executor --force)` -> `Write` was a working
three-call escape. `--force` additionally requires a TTY. Keep all four properties.

The one deterministic exception is tool permission, which is plumbing rather than judgment: `PreToolUse` denies the
write tools outright, and `handlers.bash_write_intent` string-matches shell write forms. Keep that narrow — it is a
guardrail for the ordinary paths, with the output audit as the real backstop. Do not grow it into a shell parser.

### The auditor's invariants — all load-bearing

- **It must never crash a hook or block a response.** On any failure (`is_error`, non-zero exit, timeout, unparseable
  reply, missing binary) it returns `compliant=True` with `error` set.
- **`error` carries only the exception *type name*** — never a message, never `stderr`. CLI/SDK error bodies would
  otherwise flow into user-visible LLM output (see commit `94e32bd`). Don't "improve" that by adding detail.
- **`--safe-mode` on the child `claude` call is the recursion guard.** Without it the audit call re-triggers this
  plugin's own hooks. `FORGE_AUDITOR_CHILD=1` is the second lock: every handler no-ops when it sees it.
- **Never use `--bare`.** It looks equivalent but its auth is *strictly* `ANTHROPIC_API_KEY` or `apiKeyHelper` — OAuth
  and keychain are never read. It would reintroduce the dependency this port exists to remove.

### The hook contract

- A hook must never break a session. `hookio.run()` swallows every exception and exits 0 with no output, so Claude
  Code proceeds as if the plugin were absent. `FORGE_HOOK_DEBUG=1` prints the traceback instead.
- Hook stderr is invisible from inside a running interactive session, so `FORGE_HOOK_TRACE=1` appends a JSONL trail
  to `$FORGE_STATE_DIR/audit/hooks.jsonl` (`hookio._trace`) for tailing while you drive Claude Code. It records the
  decision, not the content, and carries only an exception *type* name — same rule as the auditor's `error`. Tracing
  must never raise: a broken trace is not worth a failed hook.
- **The audit runs detached by default** (`handlers._spawn_audit` -> `forge_cc/audit_worker.py`), because the verdict
  is not needed until the next turn. The Stop hook returns in ~60ms instead of 4800-9300ms. `UserPromptSubmit`
  collects the finding, waiting at most `FORGE_AUDIT_WAIT` for a worker still in flight. Deliver it **before** the
  thinking-mode gate: the finding describes a previous thinking-mode response, so a switch to Executor must not
  swallow it. `FORGE_AUDITOR_ASYNC=0` forces the synchronous path.
- **Latency levers, measured — do not re-guess these.** `--effort low` roughly halves the call (sonnet ~4.8s ->
  ~3.0s) with no verdict changes on the calibration cases. Haiku is *slower* than sonnet here (~7.4s), needing an
  extra round-trip for the JSON schema — the input audit used to pin haiku "for speed" and was the slowest hook in
  the plugin. Process startup is negligible (`time_to_request_ms` 160-780ms); it is all model time.
- **A finding does not block by default.** `Stop` fires after the response renders, so blocking cannot prevent the
  user reading a violation — it only appends a second copy of the answer. So the default notifies in one line and
  carries the detail into the next `UserPromptSubmit` (`paths.set_pending_audit` / `consume_pending_audit`), which
  tells the model not to apologise or re-answer. `FORGE_OUTPUT_BLOCK=1` restores in-turn blocking.
- **The `Stop` hook must honor `stop_hook_active` AND its own revision budget.** Blocking on Stop re-enters the agent.
  The flag is necessary but not sufficient: measured on Claude Code 2.1.258, a second block within the same turn still
  arrives with `stop_hook_active` false, so `handlers._max_revisions()` (`FORGE_MAX_REVISIONS`, default 1) caps it and
  `UserPromptSubmit` resets the budget each turn. Do not drop either half. The budget applies to the blocking path
  only — notifications never re-enter the agent — and is checked *before* the audit runs, so an exhausted turn does
  not spend ~9s on a verdict it cannot act on.
- **Audit only assistant text written after the user's last message** (`transcript.response_under_audit`). The hook
  races Claude Code's transcript write; reading the newest assistant entry unconditionally returned the *previous*
  turn's reply and blocked a response nobody had judged, quoting a banner from two turns earlier. Waiting is bounded
  by `FORGE_TRANSCRIPT_WAIT` and auditing nothing is the correct fallback — never audit stale text.
- `PostToolUse` is the wrong event for output validation — it fires after tool calls, never after a response.
- Executor mode gets zero per-turn work: no audit, no write-lock, no checkpoints. That is a feature, not an oversight.

### Mode changes happen in the hook, not the skill

`UserPromptSubmit` detects a mode command in the user's raw prompt
(`handlers.requested_mode`) and applies the switch itself. Two reasons, both load-bearing:

- The skill body no longer shells out to `forge set-mode`, so no `Bash(...)` call and no wall of CLI JSON is rendered
  to the user for what is bookkeeping. Superpowers-style skills are pure prompt; ours should look the same.
- The switch becomes deterministic — the model cannot forget it, botch it, or reorder it relative to the rules
  injection.

`requested_mode` matches an **invocation**, never a mention: Claude Code's `<command-name>` wrapper, or a prompt
that *begins* with `/[namespace:]<mode>-mode`. Both failure directions have been hit:

- Matching only the bare `/forge-mode` meant an installed user typing `/forge-protocol:executor-mode` was refused
  their own mode switch by the consent gate.
- Matching the command *anywhere* meant "why did you suggest /executor-mode?" left the thinking mode and unlocked
  the write tools. A mode-mismatch notice instructs the model to say "that's /executor-mode", so quoting it back was
  a likely accident, not a corner case.

Prose therefore records no consent at all — the same authorisation gates the switch and the CLI, so they must agree.

### Mode changes: relaxing requires the user

This exists because a real model, denied `Write`, invoked `/executor-mode` itself and wrote the file legally. A mode
the model can leave is not a mode.

Leaving a thinking mode removes the write-lock and the audit, so `forge set-mode` refuses unless `UserPromptSubmit`
recorded a matching request from the **user's own raw prompt** (`handlers.requested_mode`). Consent is single-use.
`--force` bypasses it for humans driving the CLI directly and logs a `mode:forced-relaxation` violation.

Which transitions are gated comes from `transitions.confirm_switch` in the mode YAML: leaving a
`confirm_switch: true` mode for one that is `false` is the relaxation that needs consent, while entering a mode or
moving laterally does not. `transitions.allowed_to` is enforced too. Both fields were parsed and never read before —
in this port *and* in the Hermes original — so keep them load-bearing rather than reverting to a hardcoded mode list.

### The `modes/*.json` twins

YAML is the authored format. The committed JSON twins exist because hook handlers run under the bare system `python3`
and **a Claude Code plugin cannot declare pip dependencies** — so PyYAML may simply be absent. `lib/modes.py` falls
back to the twins when `import yaml` fails.

**Never hand-edit the JSON.** After editing any `modes/*.yaml`, re-run `python3 scripts/build_modes_json.py`.
`--check` belongs in CI.

### Adding a mode

Drop `modes/<id>.yaml` + `souls/<id>.md` (field reference: `modes/schema.yaml`, annotated but not runtime-validated;
the loader in `lib/modes.py` is forgiving), then regenerate the JSON twin. `load_all_modes()` picks up any `*.yaml`
except `schema.yaml`. For a first-class new mode you also need:

- `VALID_MODE_IDS` in `lib/modes.py`
- `ModeRatios` in `lib/audit.py` (the dependency report)
- `THINKING_MODES` in `forge_cc/handlers.py` (which modes get the write-lock and the output audit)
- `_MODE_COMMANDS` in `forge_cc/handlers.py` (so the user's slash command counts as consent)
- `agents/<id>.md` and `skills/<id>-mode/SKILL.md`

Mode rules live in **two** places by design — `behaviors`/`input_rules` in the YAML drive the validators and the
auditor, the soul and agent files drive generation. Changing one without the other makes the auditor and the model
disagree.

### `behaviors.required` vs `behaviors.conditional`

`required` is demanded of **every response**. `conditional` holds rules gated on a trigger or a cadence
("periodically ...", "once the user has stated a position", "after revision") and is a violation only when the
trigger occurred and the behavior is still absent. Keep `required` short, and state the trigger inside the rule text
so the auditor can see it.

This split is not cosmetic. With everything in `required`, the auditor demanded all seven of Forge's behaviors in
every reply, and the only way to pass was to answer seven words with five labelled forcing functions, a steelman, an
attack and a prediction demand. Calibrated friction became a wall of text — and a plugin that exhausting gets
uninstalled, which protects nobody. `tests/test_modes.py` fails if a trigger-gated rule migrates back into
`required`.

Two guardrails hold the calibration, and both are load-bearing:

- **Proportionality is encoded in the rule text**, not left to the judge — Forge's ordering rule itself says "3-5
  questions for a substantive exchange, one or two for a brief one", and every thinking mode forbids burying a brief
  message under the full apparatus.
- **Proportionality governs how much, never whether.** The auditor prompt says so explicitly, because without it the
  judge reads the whole block as licence to be lenient and stops catching a judgment-first response — which is the
  violation that matters most. An ordering rule is broken whenever the order is wrong, however brief the reply.
  `lib/auditor.py`'s prompt and `tests/test_auditor.py` pin both directions.

### Path & state resolution

- Plugin root: `CLAUDE_PLUGIN_ROOT` (set by Claude Code inside hook commands) → the directory above `forge_cc/`.
  Modes resolve via `FORGE_MODES_DIR` → `<plugin-root>/modes`.
- State is JSON files under `FORGE_STATE_DIR` or `~/.forge-state/`: `sessions/<id>.json`, a separate
  `canary_history.json`, and `current.json` (the cwd → session-id pointer plus pending mode consent). Session IDs are
  regex-restricted and path-traversal-guarded in `lib/state.py`; keep that guard when touching path construction.
  `Mode.load_system_prompt` has the equivalent guard for soul paths.
- Claude Code exports no session-id environment variable, which is why `SessionStart` writes the pointer and the CLI
  reads it back, keyed by working directory so concurrent sessions in different projects don't collide.
- Handlers that mutate a session write it once (`sm._write_session`) rather than round-tripping through
  `StateManager` helpers — intentional, to avoid redundant disk reads.

### CLI read/write separation

`state`, `rules`, `checkpoint`, `report` and `canary trend` are read-only so `/forge-status` can render a dashboard
without side effects. `checkpoint` in particular must **not** stamp `last_checkpoint_at` — the `UserPromptSubmit` hook
owns delivering checkpoints, and a read that consumed one would silently swallow it. Mutation is opt-in: `set-mode`,
`canary submit`, `report --record`, `audit-done`.

## Conventions

- Python 3.11+, type hints, `from __future__ import annotations`.
- Commits follow `type(scope): summary` (`fix(install):`, `docs(prompts):`, `security:`).

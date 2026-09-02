# Task: Port Forge Protocol to a native Claude Code plugin

## Context

Source repo: https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent

Forge Protocol is an anti-deskilling framework with four interaction modes
(Forge, Anvil, Crucible, Executor) built as a plugin for Hermes Agent
(NousResearch). Its `lib/` core is pure Python with zero Hermes dependency —
only `plugin/` and the Hermes-specific plumbing need replacing.

Your job: fork the repo, strip the Hermes plugin layer, and rebuild the same
behavior as a native Claude Code plugin using Claude Code's own primitives
(hooks, subagents, skills, and a plugin manifest). Preserve `lib/` and
`modes/*.yaml` as-is where possible — they are the portable core.

**Hard requirement: no API key.** The port must run on nothing but a working
Claude Code subscription. `ANTHROPIC_API_KEY`, `VERTEX_PROJECT`, and the
`anthropic` SDK dependency all go away — see Step 6, which replaces the
auditor's direct-API call with a headless `claude -p` subprocess that reuses
the user's existing Claude Code credentials.

Do not invent Claude Code plugin APIs. The manifest shape, hook event names,
and flag behavior recorded in this plan were verified against Claude Code
**2.1.258** on 2026-09-02 (see Step 0 for how to re-verify); anything not
recorded here, look up before you write config.

---

## Step 0 — Setup, and verify the schema with the tooling (not the docs)

1. Create a new git remote/branch for this fork rather than modifying the
   original repo's history — this is a derivative port, not a PR against
   upstream Hermes integration.
2. Don't guess (or trust this plan blindly) about plugin layout. Claude Code
   ships the authority as tooling — use it:

   ```bash
   claude plugin init probe --with skills agents hooks   # emits the canonical layout
   claude plugin validate --strict <path>                # manifest + agents + skills lint, CI-safe
   claude plugin details <name>                          # component inventory + token cost
   claude plugin eval <path>                             # behavioral eval cases (see Step 8)
   claude --plugin-dir <path>                            # load the plugin for one session, no install
   ```

   `claude plugin init` is the fastest way to see the current frontmatter and
   manifest fields; `--strict` is what belongs in CI.
3. Verified layout as of 2.1.258 — components are **auto-discovered by
   convention**, not enumerated in the manifest:

   ```
   .claude-plugin/plugin.json     # $schema, name, version, description, author{name,email}
   .claude-plugin/marketplace.json # so users can `/plugin marketplace add <repo>`
   agents/*.md                    # subagents: frontmatter name, description, tools[]
   skills/<name>/SKILL.md         # slash commands: frontmatter name, description
   hooks/hooks.json               # { "hooks": { "<Event>": [ { "hooks": [ {...} ] } ] } }
   hooks-handlers/                # the scripts hooks.json points at
   lib/ modes/ souls/             # unchanged portable core
   ```

   `${CLAUDE_PLUGIN_ROOT}` is the env var hook commands use to reach plugin
   files. There is **no** manifest field for declaring required environment
   variables — document them in the README instead (Step 9).

---

## Step 1 — Keep the portable core untouched

- Leave `lib/` as-is (`modes.py`, `state.py`, `validator.py`, `canary.py`,
  `checkpoints.py`, `audit.py`). This is pure Python, already designed with
  zero Hermes dependency. `lib/auditor.py` is the one exception — its
  transport changes in Step 6, its public API does not.
- Leave `modes/*.yaml` (forge, anvil, crucible, executor) untouched — these are
  the mode definitions (behaviors.required, behaviors.forbidden, input_rules,
  metacognitive checkpoints). They stay the source of truth.
- Leave `souls/*.md` untouched except where they name Hermes tool calls
  (Step 3). Their Cabitza-lab citations are load-bearing design rationale
  (`RESEARCH.md`) — do not paraphrase them away.
- Delete `plugin/` (the Hermes `PluginContext`-based plugin) — this is what
  you're replacing.
- Delete `forge.sh`. Replace `install.sh` with the marketplace manifest from
  Step 2 — do not just delete it and leave no install path.

### Drop the PyYAML runtime dependency on the hook path

`lib/modes.py` imports `yaml`. Hook scripts run as bare shell commands against
whatever `python3` is on `PATH`, and **a Claude Code plugin cannot declare pip
dependencies** — so `import yaml` will `ImportError` on a user whose system
Python lacks PyYAML, and the hook will fail silently-ish on every turn.

Fix, in order of preference:

1. Add a build step that compiles `modes/*.yaml` → `modes/*.json`, commit the
   JSON, and make `lib/modes.py` prefer JSON when `yaml` is unimportable. YAML
   stays the authored format; the hook path gets zero third-party deps.
2. Do **not** solve this with the `bun`-based TypeScript handler that
   `claude plugin init` scaffolds. `bun` is not guaranteed present (it was
   absent on the verification machine), and the handlers need to import `lib/`
   anyway. Use `python3`.

Keep `[dev]` in `pyproject.toml`; delete the `[auditor]` and `[vertex]` extras
(Step 6) and the top-level `pyyaml` runtime dep once (1) lands.

---

## Step 2 — Plugin manifest and marketplace entry

Create `.claude-plugin/plugin.json`:

- `name`: `forge-protocol`
- `description`: adapted from the repo's tagline ("anti-deskilling framework,
  four modes: Forge, Anvil, Crucible, Executor")
- `version`, `author` — credit Lorenzo Famiglini as original author; note this
  is an unofficial Claude Code port
- `$schema`: `https://anthropic.com/claude-code/plugin.schema.json`

Do **not** try to enumerate commands/agents/hooks as "entry points" — they are
discovered from `agents/`, `skills/`, and `hooks/hooks.json`. Do not try to
declare env vars; the manifest has no field for it.

Then add `.claude-plugin/marketplace.json` so the repo is installable straight
from git. Verified minimum shape (a self-hosting single-plugin marketplace):

```json
{
  "name": "forge",
  "description": "Forge Protocol — required, or --strict fails",
  "owner": { "name": "Lorenzo Famiglini" },
  "plugins": [
    { "name": "forge-protocol", "source": "./", "description": "…" }
  ]
}
```

That makes the install path:

```
/plugin marketplace add lorenzofamiglini/The-Forge-Protocol-Agent
/plugin install forge-protocol
```

Validate with `claude plugin validate --strict .` in CI — note that when both
manifests sit in `.claude-plugin/`, `validate` targets the **marketplace**
manifest, so lint the plugin manifest with a second invocation pointed at a
path that has only `plugin.json` (or check the CLI's current behavior).
Use `claude plugin tag` for releases (it checks plugin.json and the marketplace
entry agree).

---

## Step 3 — Subagents for delegation, hooks for enforcement

Create `agents/forge.md`, `agents/anvil.md`, `agents/crucible.md`,
`agents/executor.md` from the corresponding `souls/*.md`, using the verified
frontmatter: `name`, `description`, `tools` (a list).

- `description` decides when the router delegates — keep it short and specific.
- `tools`: restrict per mode's intent. Forge/Anvil/Crucible get read-only sets
  (`Read`, `Grep`, `Glob`); Executor gets full default access (it's the
  "normal AI, no friction" mode per the README).
- Body: the soul file's content, with Hermes mechanics removed — the souls
  reference `forge_validate_output` as a callable tool; that tool no longer
  exists. Replace those passages with "an independent auditor evaluates this
  response after you finish; its verdict is injected as context and is ground
  truth" (Step 5/6).

**Read this before you rely on subagent `tools` as an enforcement mechanism.**
The original plan claimed tool restriction on the subagent gives a "real
behavioral guarantee Claude Code can give you that Hermes's prompt-only
enforcement couldn't." It does not, on its own. A Claude Code subagent is a
delegate the main agent spawns for a bounded task and then returns from — it is
not a persona the session runs in. After `/forge-mode`, the user is still
talking to the **main** agent, which has full `Write`/`Edit`. A read-only
`tools` list on `agents/forge.md` constrains the delegate only.

So enforcement is two-layered, and the hook layer is the load-bearing one:

- **Session-level (real enforcement):** a `PreToolUse` hook that denies
  write-capable tools while a thinking mode is active, by returning
  `hookSpecificOutput.permissionDecision: "deny"` with a
  `permissionDecisionReason` naming the violated rule from the mode YAML. This
  is deterministic, harness-run, and not subject to model discretion — it is
  the genuine upgrade over Hermes's prompt-only enforcement.
- **Delegation-level:** the restricted `tools` lists above, so an explicitly
  invoked `forge` subagent is also boxed in.

Keep both. Just don't let the plan's Step 8.2 verification ("confirm
Forge/Anvil/Crucible subagents genuinely lack write/edit tool access") stand in
for the thing that actually matters — that the *session* can't write while
Forge mode is on.

---

## Step 4 — Slash commands: mostly a move, not a conversion

The repo's `skills/*/SKILL.md` files (`forge-mode`, `anvil-mode`,
`crucible-mode`, `executor-mode`, `forge-audit`, `forge-status`) are **already
in Claude Code's native skill/slash-command format** — frontmatter `name` +
`description`, markdown body. Verified against the `claude plugin init`
scaffold. This step is far smaller than it looks:

1. Move them under the plugin root's `skills/` (or leave in place and declare
   `"skills": ["./"]`).
2. Drop the `metadata.hermes` block. `version`/`author`/`license` are tolerated
   but unused; `--strict` may warn on unrecognized fields, so prune.
3. Do **not** create a parallel `commands/` directory. One mechanism, not two.
4. Bodies: replace instructions that call Hermes tools with either a shell-out
   to a small `bin/forge-state` wrapper over `lib/state.py`, or explicit
   instructions to read/write the JSON state under `FORGE_STATE_DIR` (default
   `~/.forge-state/`). Keep `lib/state.py`'s session-ID regex and
   path-traversal guard on any new path construction.
5. `/forge-audit weekly|monthly|quarterly` drives `lib/canary.py` /
   `lib/audit.py`. Note that a skill cannot block on stdin — the flow is
   "present the prompt, the user answers in the next turn, then score", not an
   interactive CLI timer.

---

## Step 5 — Replace Hermes tool-call validation with hooks

Hermes's `forge_validate_input` / `forge_validate_output` / `forge_checkpoint` /
`forge_log` were plugin tools the orchestrator chose to call. In Claude Code
they become hooks the harness always runs.

**Verified event names in 2.1.258:** `PreToolUse`, `PostToolUse`,
`UserPromptSubmit`, `SessionStart`, `SessionEnd`, `Stop`, `SubagentStart`,
`SubagentStop`, `PreCompact`, `PostCompact`, `Notification`.

- **`UserPromptSubmit`** — mode input-rule validation (`lib/validator.py`'s
  input rules for the active mode: e.g. Anvil requires a full draft, not a
  fragment dump) plus the thinking-vs-execution task classification ported from
  `souls/forge-orchestrator.md`. Block with a reason, or annotate via
  `hookSpecificOutput.additionalContext` — see the latency budget below before
  choosing.
- **`Stop` and `SubagentStop`** — output validation against `lib/validator.py`'s
  output rules (Forge must never converge to a single recommendation; Anvil
  must never rewrite), and where the adversarial auditor runs (Step 6).
  **`PostToolUse` is the wrong event for this** — it fires after tool calls,
  never "after the agent produces its response." A blocking `Stop` hook is the
  right primitive for "you must revise", but it re-enters the agent, so it
  **must** check `stop_hook_active` in its input and stop blocking once set, or
  the session loops forever.
- **`PreToolUse`** — the write-lock from Step 3.
- **`SessionStart` / `SessionEnd`** — read/write session files under
  `FORGE_STATE_DIR` and append to the audit log (`lib/audit.py`), replacing
  `forge_log`. `SessionStart` is also where you inject the active mode's soul
  as `additionalContext`, which is what actually makes the *session* run in a
  mode.
- **Metacognitive checkpoints** (`lib/checkpoints.py`) — fire from the same
  `Stop` hook on the configured interval, injecting the checkpoint prompt into
  the next turn.

Write these as `python3` scripts under `hooks-handlers/`, registered in
`hooks/hooks.json` with `${CLAUDE_PLUGIN_ROOT}`-relative paths. Confirm from
the docs how each event's stdin JSON and exit codes are shaped before writing,
and set an explicit per-hook `timeout` — the default is short relative to an
LLM round-trip (Step 6 measured ~6s).

### Latency budget — do not put a blocking LLM call on every prompt

One `claude -p` judgment measured **6.1s wall / ~$0.004 list** (Sonnet, 850
input tokens). On `UserPromptSubmit` that is 6s added to *every* turn, which
will get the plugin uninstalled. Mitigations, all of which should land:

- Run the input audit only when a thinking mode is active — Executor mode skips
  it entirely (`input_rules` is empty there anyway).
- Use `--model haiku` for input-rule checks; reserve Sonnet/Opus for the output
  audit, where strictness is the point.
- Make the input audit **advisory** (`additionalContext`) and the output audit
  the strict/blocking one. The mode's job is to change how the model engages,
  and injected context does that without a turn-latency tax.
- Consider short-circuiting on the cheap deterministic signals first (is there
  a draft at all? is the state file's mode a thinking mode?) and only calling
  the auditor when those pass.

---

## Step 6 — Port the auditor to run on the Claude Code subscription

The auditor's *design* is untouched: an independent model instance judges
compliance, because an LLM asked to grade its own output rubber-stamps itself
(README). Only the transport changes — and it changes to remove the API key.

**Delete** from `lib/auditor.py`: `_build_client()`, the `anthropic` /
`AnthropicVertex` imports, `_extract_json()`, and every mention of
`ANTHROPIC_API_KEY`, `VERTEX_PROJECT`, `VERTEX_REGION`, `FORGE_AUDITOR_BACKEND`.
Delete the `[auditor]` and `[vertex]` extras from `pyproject.toml`.

**Replace** `_invoke()` with a subprocess call to the `claude` CLI already on
the user's machine. Verified working with `ANTHROPIC_API_KEY` unset:

```bash
claude -p "<user prompt>" \
  --model sonnet \
  --system-prompt "<_OUTPUT_AUDIT_SYSTEM>" \
  --json-schema '{"type":"object","properties":{...},"required":[...],"additionalProperties":false}' \
  --output-format json \
  --tools "" \
  --safe-mode \
  --no-session-persistence
```

Why each flag matters:

| Flag | Why |
|---|---|
| `--model sonnet` | Accepts aliases (`opus`/`sonnet`/`haiku`) or full ids. This is what `FORGE_AUDITOR_MODEL` now feeds. |
| `--system-prompt` | Replaces the default system prompt outright — the auditor must not inherit Claude Code's coding-agent persona. (`--append-system-prompt` would.) |
| `--json-schema` | Server-side structured-output validation. The response JSON carries a parsed `structured_output` object, so `_extract_json()`'s brace-scraping heuristic is deleted, not ported. |
| `--output-format json` | Gives `is_error`, `subtype`, `result`, `structured_output`, `usage`, `total_cost_usd`. Parse `structured_output` first; fall back to `result`. |
| `--tools ""` | Disables all tools. The auditor is a judge, not an agent — no filesystem, no bash, no web. |
| `--safe-mode` | **This is the recursion guard.** It disables plugins, hooks, CLAUDE.md, skills, and MCP for the child process, so the nested call does not re-trigger Forge Protocol's own `SessionStart`/`UserPromptSubmit`/`Stop` hooks. Critically, its help states auth, model selection, built-in tools, and permissions still "work normally" — subscription credentials are read as usual. Also set a `FORGE_AUDITOR_CHILD=1` env var and have every hook handler no-op when it sees it, as belt-and-braces. |
| `--no-session-persistence` | Keeps audit calls out of the user's `/resume` history. |

**Never use `--bare` here.** It looks attractive (it skips hooks and plugin
sync) but its auth is *strictly* `ANTHROPIC_API_KEY` or `apiKeyHelper` — OAuth
and keychain are never read. It would reintroduce exactly the dependency this
port exists to remove. `--safe-mode` is the flag that gives you isolation while
keeping subscription auth.

Config surface after the port:

```
FORGE_AUDITOR_ENABLED   "1" to enable
FORGE_AUDITOR_MODEL     CLI model alias or id (default: sonnet)
FORGE_AUDITOR_CMD       path to the claude binary (default: "claude" on PATH)
FORGE_AUDITOR_TIMEOUT   subprocess timeout in seconds (default: 60)
```

Two things to preserve verbatim from the current implementation:

- **The auditor must never crash a tool call or block a response.** On any
  failure — non-zero exit, timeout, `is_error: true`, unparseable JSON,
  `claude` not on `PATH` — return `compliant=True` with `error` set.
- **`error` carries only the exception type name, never the message.** Commit
  `94e32bd` did this deliberately: SDK/CLI error bodies would otherwise flow
  into user-visible LLM output. A subprocess makes this *more* important, not
  less — never put `stderr` in `error`.

Two things that change for the better:

- **Default it on.** `FORGE_AUDITOR_ENABLED` defaulted to off because it needed
  a key and a paid extra. With neither required, the honest default is enabled,
  with graceful fallback to orchestrator self-evaluation when `claude` isn't
  resolvable. Keep both code paths working — `audit_*` returning `None` for
  "self-evaluate instead" is still the contract.
- Same treatment for `score_canary()` (Step 7) — it shares the transport.

**Tell the user what it costs.** There's no dollar charge on a subscription,
but each audit consumes Claude Code usage limits, and the returned
`total_cost_usd` is list-price accounting, not a bill. Document that in the
README, and consider `--max-budget-usd` as a safety valve.

---

## Step 7 — Canary / self-audit system

Port `lib/canary.py` unchanged; it needs no transport of its own. Wire
`/forge-audit weekly` (Step 4) to: display the prompt → user answers unassisted
in the next turn → `score_canary()` scores it through the Step 6 subprocess →
append to `FORGE_STATE_DIR/canary_history.json` → report change vs. previous,
mean of last 5, and linear slope, as the original CLI flow describes.

Note that `canary_history.json` is deliberately a separate file from
`sessions/<id>.json` — keep it that way.

---

## Step 8 — Test

1. The suite is **85 tests**, but "most should pass unchanged" is optimistic.
   Accurate split:
   - **59 pass unchanged** — `test_modes.py` (13), `test_state.py` (14),
     `test_validator.py` (9), `test_canary.py` (13), `test_checkpoints.py` (10).
   - **15 must be rewritten** — `test_plugin.py` calls the Hermes `_handle_*`
     handlers directly. Retarget them at the new hook handlers, keeping the
     same behavioral assertions. Run with `FORGE_STATE_DIR=$(mktemp -d)`; the
     originals polluted `~/.forge-state/`.
   - **11 must be rewritten** — `test_auditor.py` injects a fake client and
     mocks `client.messages.create`. Replace that seam with a fake
     `claude` executable on `PATH` (or an injectable runner function) so the
     never-crash and error-sanitization contracts stay covered. Add cases for:
     binary missing, non-zero exit, timeout, `is_error: true`, valid
     `structured_output`, and garbage on stdout.
   - Add tests asserting no import of `anthropic` anywhere, and that
     `ANTHROPIC_API_KEY` appears nowhere in the tree.
2. Note `python3 -m pytest`, not bare `pytest` — the repo root isn't on
   `sys.path` unless installed editable.
3. Behavioral verification is what `claude plugin eval` is for — write eval
   cases (`evals/**/case.yaml` or `prompt.md` + `graders/*.md`) for the
   boundaries that actually matter:
   - Forge mode active → a prompt that begs for a written answer → assert the
     response converges on nothing and the `PreToolUse` write-lock fired.
   - Anvil mode + a fragment dump → assert `UserPromptSubmit` blocked or
     annotated rather than passing through.
   - Auditor enabled with the API key unset → assert an `audit` verdict appears
     and no auth error surfaces.
   - Auditor with `claude` unresolvable → assert the response still completes.
4. Manually confirm the recursion guard: run with `--debug hooks` and check the
   nested auditor call fires no Forge hooks of its own.

---

## Step 9 — Docs

Update `README.md`'s Quick Start / Architecture / Project Structure for the
Claude Code path (`/plugin marketplace add …` → `/plugin install forge-protocol`),
and lead with "no API key required — works on your Claude Code subscription,"
since that's the headline difference from the Hermes original. Document the
four env vars from Step 6 and the usage-limit note.

Update `CLAUDE.md`: the three-layer architecture description, the
"Adding a mode" checklist (`VALID_MODE_IDS`, the `SET_MODE_SCHEMA` enum — which
becomes whatever replaces it — and `ModeRatios` in `lib/audit.py`), the
enforcement section (validator still returns rules for LLM judgment; regex is
still never the mechanism), and the installer notes, which no longer apply.

Keep `RESEARCH.md` as-is — it's the theoretical grounding, not
implementation-specific. Add a note crediting Lorenzo Famiglini's original
Hermes-based project and linking back, per the MIT license terms.

---

## Deliverable

A working Claude Code plugin (`.claude-plugin/` manifest + marketplace entry,
`agents/`, `skills/`, `hooks/` + `hooks-handlers/`, and an otherwise untouched
`lib/` and `modes/`) that reproduces mode switching, input/output validation
per mode, genuinely enforced tool restrictions, metacognitive checkpoints, the
independent auditor, and the canary skill-tracking system — installable in
Claude Code without Hermes Agent, **and runnable with no API key, no cloud
project, and no `anthropic` SDK installed.**

---

## Implementation status

Implemented on branch `feat/claude-code-port`. What follows records where the
build deviated from the plan above, so the plan is not mistaken for the truth
— `README.md` and `CLAUDE.md` describe what actually exists.

**Added, not in the plan:**

- **`forge_cc/` as a fourth layer.** The plan implied hook scripts calling
  `lib/` directly. That would have put Claude-Code-specific logic in `lib/`
  or duplicated it across six shims, so the host-aware code lives in one
  package (`handlers`, `cli`, `hookio`, `paths`, `transcript`) with
  `hooks-handlers/*.py` and `bin/forge` as thin shims over it. Handlers are
  plain `dict -> dict` functions, which is what makes them testable.
- **`bin/forge`** — a JSON-emitting CLI the skills shell out to, since a
  Claude Code skill is a prompt and cannot call Python directly. Read/write
  separation is deliberate (`state`/`rules`/`checkpoint`/`report` mutate
  nothing) so `/forge-status` cannot swallow a pending checkpoint or clear an
  overdue reminder as a side effect of being displayed.
- **The mode-relaxation consent gate.** The first live session test found the
  hole the plan never anticipated: denied the `Write` tool, the model invoked
  `/executor-mode` itself, left Forge mode, and wrote the file legally.
  `set-mode` now refuses to leave a thinking mode without a request recorded
  from the user's own raw prompt. Without this the write-lock is decorative.
- **`Bash` write-intent detection.** The plan's write-lock covered only the
  file tools. Shell redirects, `tee`, `dd`, `truncate`, `install` and in-place
  edits are now denied too. Narrow on purpose; the output audit is the backstop.
- **`souls/forge-orchestrator.md` rewritten and injected at `SessionStart`.**
  The plan had no home for it, which would have dropped the
  thinking-vs-execution classifier — and since Executor is the default mode,
  the protocol would never have nudged a user who parks there. Once per
  session, zero per-turn cost.
- **`scripts/verify_enforcement.py`** — 50 checks that spawn the real hook
  shims as subprocesses, plus `--live` for one real auditor call. This is what
  Step 8.2's "manually verify each mode boundary" turned into.

**Not done:**

- **Step 8.3's `claude plugin eval` suite.** `plugin eval` is gated behind
  early access and is not enabled for this account, so the `case.yaml` schema
  could not be verified. Rather than invent one, the behavioral checks went
  into `scripts/verify_enforcement.py`. Revisit when eval access lands.

**Corrected from the plan:**

- Step 8's test split was optimistic in both directions. Final suite is **274
  tests** — `test_plugin.py` deleted, `test_auditor.py` rewritten,
  `test_canary.py` touched for the `client=` → `runner=` rename, and five new
  files (`test_auditor_transport.py`, `test_handlers.py`, `test_cli.py`,
  `test_transcript.py`, `test_mode_guard.py`).
- `pyproject.toml` now has **no runtime dependencies at all**; PyYAML moved to
  `[dev]`, since the JSON twins cover the hook path.

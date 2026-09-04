# Orchestrator Routing Fix Plan

Status: awaiting review and execution approval

Branch: `fix/orchestrator-routing`

## Problem

The Forge orchestrator is injected at session start and correctly classifies
thinking tasks, but it currently acts only as a mismatch notifier. When a
thinking request arrives in the default Executor mode, the orchestrator warns
the user and then continues answering in Executor instead of activating Forge,
Anvil, or Crucible.

Mode state changes are also tied to explicit `$<mode>-mode` or `/<mode>-mode`
invocations. This conflicts with the mode skills' semantic trigger descriptions:
a host may implicitly select a mode skill for a matching task even though the
explicit-command hook has not changed the active mode.

## Desired behavior

The orchestrator should classify every request and automatically route a task
from the default Executor fallback into the applicable thinking mode:

- Forge for reasoning, design, strategy, and requests that need the user's own
  judgment.
- Anvil when the user supplies a substantial draft for critique.
- Crucible when the user supplies at least three ideas to pressure-test.
- Executor for genuinely mechanical transformation or execution.

An explicit user mode selection remains authoritative. Automatic routing may
add or preserve cognitive friction, but it must never relax a thinking mode to
Executor without an explicit user invocation.

## Implementation plan

### 1. Track mode ownership

Add a mode-selection source to session state so routing can distinguish the
initial Executor fallback from a user's deliberate choice:

- `default`: the initial Executor fallback.
- `user`: an explicit mode-skill invocation.
- `orchestrator`: an automatic route selected from the task.
- `legacy`: a session loaded from state that predates this field.

Treat `legacy` conservatively like an explicit selection. An explicit invocation
of the already-active mode must still change its source to `user`; selecting
`/executor-mode` while already in Executor is meaningful consent, not a no-op.

Keep state deserialization backward-compatible and expose the current source in
the status output so routing decisions are inspectable.

### 2. Add a constrained automatic-routing command

Add:

```text
forge route-mode <forge|anvil|crucible>
```

The command should:

- Accept routes only when the current source is `default` or `orchestrator`.
- Permit Executor-to-thinking and thinking-to-thinking transitions.
- Reject Executor as an automatic target.
- Reject attempts to override a `user` or `legacy` selection.
- Honor `transitions.allowed_to` and the mode definitions.
- Provide no `--force` option.
- Record the resulting source as `orchestrator`.

The existing explicit `set-mode` path remains the user-controlled path for
relaxation. The new command must not create a way around the thinking-mode write
lock or output audit.

### 3. Restore mandatory orchestrator routing

Update `souls/forge-orchestrator.md` so that classification has an action:

1. Classify the request before answering.
2. Determine whether the current mode source permits automatic routing.
3. Select exactly one applicable mode skill.
4. Activate that skill and apply the constrained route before doing substantive
   work.
5. Follow the selected mode's entry requirements and behavioral rules.

When default Executor receives a thinking task, the orchestrator must not emit a
warning followed by the requested artifact. It must route to the selected
thinking mode. A mismatch notice remains appropriate when an explicit user mode
selection cannot be overridden.

### 4. Repair mode-skill activation

Update the Forge, Anvil, and Crucible skills to support both activation paths:

- Explicit activation: `UserPromptSubmit` has already applied the user's mode
  selection.
- Implicit activation: the orchestrator selected the skill from the task, so the
  skill applies `forge route-mode <mode>` before continuing.

Ensure the selected mode's full instructions govern the routing turn and remain
available on later turns. Explicit switches should inject the target soul in the
same turn; automatic routes should arrange target-soul injection without dumping
the full prompt or CLI JSON into the user-visible response.

The Executor skill must remain user-controlled when it would relax a thinking
mode. Semantic matching alone must not unlock write tools.

### 5. Use skills as the cross-host routing targets

Follow the skill-first pattern used by Superpowers:

- `forge-orchestrator.md` is the always-active bootstrap/router.
- The four mode skills are the universal routing targets.
- Skill names and descriptions provide the host with concise classification
  metadata; the selected `SKILL.md` supplies the full workflow and rules.
- Correct routing and enforcement must work in the main agent without requiring
  named custom-agent configuration.
- Existing `agents/*.md` files may remain optional delegation targets on hosts
  that expose them, but behavior must not depend on their availability.

Do not add `.codex/agents` files merely to implement routing. Subagent delegation
is a separate optimization from selecting and activating the appropriate mode.

### 6. Preserve context and enforcement boundaries

Keep semantic classification in the orchestrator prompt layer. Do not add a
Python regex classifier or a per-prompt model call in the hook.

Hooks and the CLI remain responsible for deterministic state and enforcement:

- User invocations establish explicit ownership.
- Automatic routing can only enter or move between thinking modes.
- Only explicit user consent can relax to Executor.
- Thinking-mode write locks, input rules, checkpoints, and output audits operate
  against the automatically selected active mode.

### 7. Add regression coverage

Add focused tests for:

- New sessions starting in Executor with source `default`.
- Explicit selection of the already-active mode changing the source to `user`.
- Backward-compatible loading of state without a source field.
- Executor-to-Forge, Executor-to-Anvil, and Executor-to-Crucible automatic routes.
- Orchestrator-owned thinking-to-thinking transitions.
- Refusal to route automatically to Executor.
- Refusal to override explicit or legacy selections.
- Enforcement of YAML transition constraints.
- Mode mentions remaining non-invocations.
- Correct target-soul injection after explicit and automatic transitions.
- Prompt-contract checks requiring routing rather than warn-and-continue output.

Tests must not make network or model calls. Prompt behavior should be covered by
assembled-context and policy-contract assertions, followed by manual host smoke
tests for semantic classification.

## Acceptance scenarios

### Design request from default Executor

Given a fresh session and a request to design a chunked Burrows-Wheeler
transform that outperforms BWA-MEM3, the orchestrator should select Forge and
ask the user to define the efficiency metric, hardware assumptions, reference
size, chunk semantics, correctness requirements, and benchmark methodology. It
must not produce the algorithm first.

### Draft critique

Given a fresh session and a substantial user-authored draft requesting critique,
the orchestrator should select Anvil and apply its human-first entry and critique
rules.

### Idea pressure test

Given a fresh session and at least three user-authored candidate approaches, the
orchestrator should select Crucible and pressure-test those ideas without adding
its own.

### Mechanical request

Given a formatting, translation, or known-input transformation request, the
orchestrator should leave the session in Executor and complete it normally.

### Explicit Executor choice

Given an explicit user invocation of Executor followed by a thinking task, the
orchestrator should respect that choice. It may issue the bounded mismatch
notice, but it must not silently switch modes.

### No automatic relaxation

Given an active thinking mode, a mechanical task should result in a suggestion
to invoke Executor. The model must not switch to Executor itself.

## Verification

Run the repository's full verification sequence:

```bash
uv run --extra dev python -m pytest -q
uv run --extra dev python scripts/build_modes_json.py --check
python3 scripts/verify_enforcement.py
claude plugin validate --strict .
```

Then perform clean-session smoke tests in both Codex and Claude Code using the
acceptance scenarios above. Confirm that automatic skill routing occurs, mode
state reports the expected source, and no thinking-task artifact is produced in
Executor before routing.

## Non-goals

- No deterministic keyword or regex task classifier.
- No additional network or model call for routing.
- No new MCP server or runtime dependency.
- No automatic transition from a thinking mode to Executor.
- No redesign of the four mode definitions or their research-backed behavior.
- No requirement for named custom agents or subagent availability.

## Stop condition

Stop when all automated checks pass and both host smoke tests demonstrate that
default Executor routes thinking tasks into the correct mode while explicit user
choices and the no-relaxation invariant remain intact. Do not expand into mode
redesign, new providers, or unrelated prompt cleanup.

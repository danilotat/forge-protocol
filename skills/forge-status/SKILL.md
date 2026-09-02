---
name: forge-status
description: Show the Forge Protocol dashboard — active mode, message and violation counts, mode history, next checkpoint, and overdue audits. Use when the user runs /forge-status or asks "what mode am I in", "forge status", "how much am I using Executor mode", or how their AI dependency or canary trend is tracking.
---

# Forge Status

Show a dashboard of your current Forge Protocol state.

Run the `forge` CLI at the absolute path given as `FORGE_CLI:` in the Forge Protocol session context; if that line is absent, fall back to `${CLAUDE_PLUGIN_ROOT}/bin/forge`. Commands below write that path as `<FORGE_CLI>`.

## How to Check

```bash
<FORGE_CLI> state
```

One read-only call covers the whole dashboard. Render it as a short summary, not raw JSON:

- **Current mode** — `mode_name` and `mode_description` (Forge, Anvil, Crucible, or Executor)
- **Message count** in this session — `message_count`
- **Violations** — `violation_count`, plus `recent_violations` (the last 5, each with `rule_id`, `mode`, `type`) if the count is non-zero. Name the rules that were actually broken; a bare number tells the user nothing they can act on.
- **Mode history** — `mode_history`, each entry a mode and how many messages were spent in it
- **Next checkpoint** — `messages_until_checkpoint`, the messages left before the next metacognitive prompt fires (null in Executor mode, which has no checkpoints)
- **Audit reminders** — one line per entry in `audit_reminders`, each ending with the command that clears it: `/forge-audit weekly` for type `canary`, `/forge-audit monthly` for `stress_test`, `/forge-audit quarterly` for `dependency`. If the array is empty, say all audits are current. Never quietly drop a reminder — an unmentioned overdue canary is the failure mode this dashboard exists to prevent.

`<FORGE_CLI> checkpoint` is available and read-only (it reports `due`, `prompt`, `messages_until_next`, `current_mode` and consumes nothing), but `state` already carries the countdown — reach for `checkpoint` only if the user wants to see the pending prompt text itself. Checkpoints are delivered by the session hooks, not by this skill.

For the cross-session picture:

```bash
<FORGE_CLI> report
```

Read-only unless given `--record` (which `/forge-audit quarterly` passes, and this skill must not). Returns `total_sessions`, `total_messages`, `mode_ratios` (`forge`, `anvil`, `crucible`, `executor`), `total_violations`, and `assessment`. Show the mode ratios whenever the user is asking about their habits rather than just "what mode am I in" — the ratio is the number that reveals delegation drift. If `assessment` starts with `WARNING`, lead with it.

For the unassisted-skill trend:

```bash
<FORGE_CLI> canary list
```

Each question comes back with `attempts`, `scored_attempts`, `unscored_attempts`, and `last_score`, so this one call tells you which prompts the user has actually taken. For those with `scored_attempts` above 0, pull the full picture:

```bash
<FORGE_CLI> canary trend <prompt_id>
```

Report `last_score`, `change_vs_prev`, `mean_last_5`, and `slope_per_attempt` as they come back — a negative or flat slope goes first, unsoftened. If `unscored_attempts` is above 0, say so: those answers were recorded but never scored, there is no rescore, and they inflate `attempts` without moving the trend. If every question shows `attempts: 0`, say the canary has never been run and point at `/forge-audit weekly`.

## Interpreting Results

- **High violation count** → The AI is struggling to stay in mode. Check `recent_violations` for which rule keeps breaking, and consider reinforcing that mode's soul/subagent definition.
- **Heavy executor usage** → You may be delegating thinking tasks. Try switching to Forge mode. Executor is the one mode that runs the AI-first (Rams) pattern — fine for mechanical work, corrosive when judgment is at stake (Cabitza et al. 2023).
- **Overdue audits** → Time to test your unassisted skills. Run `/forge-audit`. Dell'Acqua et al.'s 2024 RCT found a 17% unassisted-performance drop that participants failed to notice, which is why this is measured rather than recalled. See [RESEARCH.md](../../RESEARCH.md).

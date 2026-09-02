---
name: forge-audit
description: Run a Forge Protocol self-audit — weekly canary, monthly stress test, or quarterly dependency review. Use when the user invokes forge-audit ($forge-audit in Codex, /forge-audit in Claude Code), asks to test their skills without AI, or when an audit reminder is overdue.
---

# Forge Audit — Self-Assessment System

Test your unassisted skills to prevent AI dependency from eroding your capabilities.

Run the `forge` CLI at the absolute path given as `FORGE_CLI:` in the Forge Protocol session context; if that line is absent, fall back to `${CLAUDE_PLUGIN_ROOT}/bin/forge`. Commands below write that path as `<FORGE_CLI>`.

Start by checking what is actually due:

```bash
<FORGE_CLI> state
```

The `audit_reminders` array says which audits are overdue, each with a `type` (`canary`, `stress_test`, or `dependency`), a `message`, and `overdue_days`. If the user invoked the skill with no argument, lead with the overdue ones; if the array is empty, say all audits are current and ask which of the three they want.

## Audit Types

### Weekly Canary (`forge-audit weekly`)

A timed challenge you complete **without AI assistance**:
- A fixed set of writing, analysis, debugging, strategy, and communication prompts (stable IDs so you take the same one repeatedly)
- 5-10 minute time limit
- Your answer is scored by an independent Claude auditor on clarity, depth, and independence
- Scores are stored across weeks — you see trend, change vs. previous, mean of last 5, linear slope
- Purpose: measure, not just remind. If your independence score drifts down, the canary catches it before you do.

### Monthly Stress Test (`forge-audit monthly`)

A harder challenge requiring sustained unassisted work:
- Complete a significant task without AI for 30-60 minutes
- Compare output quality to your AI-assisted baseline
- Purpose: verify you can still perform under pressure

### Quarterly Dependency Audit (`forge-audit quarterly`)

Review your AI usage patterns across all sessions:
- Mode ratios (are you living in Executor mode?)
- Violation trends (is the AI breaking mode rules more often?)
- Skill progression (are canary scores improving or declining?)
- Purpose: macro-level view of your cognitive sovereignty

## Weekly canary — the flow

1. **List the prompts and their history.**

   ```bash
   <FORGE_CLI> canary list
   <FORGE_CLI> canary list --category writing
   ```

   Categories are `writing`, `analysis`, `debugging`, `strategy`, and `communication`. Each question returns `id`, `category`, `prompt`, `time_limit_minutes`, and its history: `attempts`, `scored_attempts`, `unscored_attempts`, `last_score`. **Use the history to choose**: a prompt the user has already taken is worth more than a fresh one, because the trend is the measurement. Prefer the highest `scored_attempts`, honoring a category the user asks for.

2. **Present exactly ONE prompt** — its `prompt` text and its `time_limit_minutes`. Not the whole set: seeing five prompts lets the user shop for the easy one, and the trend only means something if they keep taking the same prompt. Say which one you picked and why (e.g. "this is your 4th time on this one — that's what makes the slope readable").

3. **State the time limit and be honest about who enforces it.** A skill cannot block on stdin and cannot run a timer — there is no countdown here. Tell the user the limit, ask them to time themselves, and say plainly that the rule is unassisted: no AI drafting, no autocomplete, no search. Then stop. Do not draft an answer, sketch an outline, hint at a structure, or "get them started" — a single hint invalidates the independence score you are about to record.

4. **Score what they actually wrote.** When their answer arrives in the next turn, pipe it to the CLI on stdin — `--response-file -` reads stdin, so nothing needs to be written to disk (and `Write` is denied anyway if a thinking mode is active):

   ```bash
   <FORGE_CLI> canary submit writing_email_decline --response-file - <<'ANSWER'
   ...the user's answer, pasted verbatim...
   ANSWER
   ```

   Keep the heredoc delimiter quoted so the shell expands nothing, and copy the response exactly — do not fix typos, tighten sentences, or reformat. The auditor scores clarity, depth, and *independence*; any editing on the way in measures your writing instead of theirs. Submitting also stamps the weekly canary as completed, so its reminder clears.

5. **Report the result.** The reply carries `attempt` (`overall`, `dimensions`, `notes`, `auditor_model`, `error`) and `trend` (`attempts`, `last_score`, `prev_score`, `change_vs_prev`, `mean_last_5`, `slope_per_attempt`). To re-read the trend later without submitting anything:

   ```bash
   <FORGE_CLI> canary trend <prompt_id>
   ```

6. **Do not soften a bad trend.** If `change_vs_prev` is negative, or `slope_per_attempt` is flat or negative, that goes in your first sentence — not buried under the dimensions that held up. No "great effort", no reframing a decline as "consolidating". A sycophantic reading of this number destroys the only measurement the framework has. On a first attempt (`prev_score` and `slope_per_attempt` come back null) say there is no trend yet rather than inventing one.

   If `attempt.error` is set the response was **stored but not scored**. Run `<FORGE_CLI> doctor` and report `auditor.available` and `auditor.resolved_command` — the auditor runs on the user's Claude subscription and needs no API key, so a failure here is a broken command path or a timeout, not missing configuration. There is no rescore: an unscored attempt stays unscored, counts toward `attempts`, and contributes nothing to the trend. When `canary list` shows `unscored_attempts` above 0, say so out loud with the number — otherwise `attempts: 6, scored_attempts: 3` silently reads as six data points when only three are real.

## Monthly stress test — the flow

There is no scoring for this one — it is an offline exercise. Present an unassisted 30-60 minute challenge drawn from the user's real work, state that the time and the no-AI rule are on their honor, and stop. When they report back, compare the outcome to their AI-assisted baseline conversationally and honestly. Then, **only once they confirm they actually did it**, clear the reminder:

```bash
<FORGE_CLI> audit-done stress_test
```

The reply returns `remaining_reminders` — the audit types still overdue. Mention them. Never run `audit-done` on the user's behalf before they have done the work; it is the one command here that can make the dashboard lie.

## Quarterly dependency audit — the flow

```bash
<FORGE_CLI> report --record
```

Returns `total_sessions`, `total_messages`, `mode_ratios` (`forge`, `anvil`, `crucible`, `executor`), `total_violations`, and `assessment` across every session. `report` is read-only by default — **`--record` is required here**, and it is what stamps the audit as completed so the quarterly reminder clears (confirm via `recorded_as_completed` in the reply). **If `assessment` starts with `WARNING`, lead with it** before any of the numbers. Then show the mode ratios against the healthy targets below and say which way the gap runs.

## Healthy Targets

- **Mode split**: ~40% Forge/Crucible, ~30% Anvil, ~30% Executor
- **Canary trend**: stable or improving over 4+ weeks
- **Violation rate**: decreasing over time (AI learning to stay in mode)

## Why this is measured, not just recommended

The canary exists because self-reported dependency is unreliable: Dell'Acqua et al.'s Wharton/PNAS RCT (2024) found a **17% decline in unassisted performance** after one week of AI use — a drop the participants did not notice. The quarterly mode-ratio review targets the same failure at the level of habit, and the epistemic-sclerosis and convergence findings (Natali, Marconi, Dias Duran, Miglioretti & Cabitza 2025; Doshi & Hauser 2024) are why a flat slope counts as a finding rather than a plateau. Full derivation in [RESEARCH.md](../../RESEARCH.md).

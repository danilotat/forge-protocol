<div align="center">

# Forge Protocol

### The AI that refuses to think for you.

**An open-source framework that rewires how AI responds — so you stay sharp.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Claude Code plugin](https://img.shields.io/badge/plugin-Claude%20Code-D97757.svg)](https://claude.com/claude-code)
[![No API key](https://img.shields.io/badge/API%20key-not%20required-brightgreen.svg)](#quick-start)
[![Research paper](https://img.shields.io/badge/paper-RESEARCH.md-8A2BE2.svg)](RESEARCH.md)

**No API key. No cloud project. No SDK.** A working Claude Code subscription is the only requirement.

[Quick Start](#quick-start) | [Why This Exists](#why-this-exists) | [The 4 Modes](#the-4-modes) | [How Enforcement Works](#how-enforcement-works) | [Configuration](#configuration) | [Measure Your Sovereignty](#measure-your-cognitive-sovereignty) | [For Educators](#for-schools--universities) | [Architecture](#architecture)

</div>

---

## The Problem

A [2024 Wharton/PNAS study](https://www.pnas.org/) found that **workers who used AI became 17% worse** at doing tasks independently — after just one week. The more they relied on AI, the less they could think without it.

This isn't a bug. It's the default behavior of every AI assistant: you ask, it answers, your skills atrophy.

**Forge Protocol changes the default.**

Instead of giving you answers, it gives you **better questions**. Instead of writing your email, it **critiques your draft**. Instead of generating ideas, it **stress-tests yours**.

> "The goal is not to slow you down. It's to keep you in the driver's seat of your own thinking."

---

## Why This Exists

Every AI tool today optimizes for one thing: **get the human to the answer as fast as possible**. That's great for productivity. It's terrible for learning.

Research calls this **deskilling** — the gradual erosion of human capabilities through automation. Forge Protocol's design is lifted directly from the empirical programme run by Federico Cabitza's lab at Milano-Bicocca, which has spent a decade showing *how* AI deskills users and *which interaction patterns* prevent it:

| Study | Finding |
|-------|---------|
| Dell'Acqua et al., Wharton/PNAS RCT (2024) | 17% performance decline after AI assistance removed |
| Cabitza et al. (2023) — *Rams, hounds and white boxes*, Artificial Intelligence in Medicine | Human-first "Hounds" ordering preserved independent judgment; AI-first "Rams" collapsed it through anchoring (12 radiologists + 44 ECG readers) |
| Cabitza et al. (2024) — xAI 2024 Best Paper | **White-box paradox** — articulate AI explanations *increase* uncritical acceptance rather than decrease it |
| Cabitza et al. (2025) — *Five Degrees of Separation* | Displacement protocol (human and AI work independently then combine) reaches 87–89% accuracy across radiology, ECG, endoscopy |
| Natali, Marconi, Dias Duran, Miglioretti & Cabitza (2025) | Four deskilling types: cognitive, semiotic, social, moral — plus **epistemic sclerosis** at team level |
| Famiglini et al. (2024) — *Never tell me the odds*, AI in Medicine Vol 150 | **Pro-hoc explanations** (commitment before explanation) prevent anchoring that post-hoc explanations cause |
| Doshi & Hauser (2024) | AI-assisted creative outputs are **5% more similar to each other** than human-only outputs — convergence as a measurable deskilling signal |
| Bjork & Bjork (1994); Parasuraman & Manzey (2010) | "Desirable difficulties" and automation-complacency thresholds — cognitive-science foundations |

> **Forge Protocol doesn't cite these papers — it implements them.** The four modes map one-to-one onto protocols empirically validated in the Cabitza lab: Forge = judicial AI paradigm, Anvil = Hounds, Crucible = frictional AI + programmed inefficiencies, Executor = Rams (the only context where AI-first is acceptable). The project's maintainer, Lorenzo Famiglini, is a co-author on the Cabitza lab's XAI-design and conformal-prediction work that these patterns draw from. See [RESEARCH.md](RESEARCH.md) for the full mapping.

---

## The 4 Modes

<table>
<tr>
<td width="25%" align="center">

### Forge

**Thinking Partner**

Asks questions.
Never gives answers.
Forces you to reason.

`/forge-mode`

*Judicial AI paradigm<br>(Cabitza et al. 2025)*

</td>
<td width="25%" align="center">

### Anvil

**Editor / Critic**

Rates your draft.
Finds weaknesses.
Never rewrites.

`/anvil-mode`

*Hounds protocol<br>(Cabitza et al. 2023)*

</td>
<td width="25%" align="center">

### Crucible

**Idea Stress-Tester**

Steelmans, then attacks.
Maps blind spots.
Never fills gaps.

`/crucible-mode`

*Frictional AI<br>(Cabitza et al. 2024)*

</td>
<td width="25%" align="center">

### Executor

**Normal AI**

Full automation.
No friction.
For mechanical tasks only.

`/executor-mode`

*Rams protocol<br>(only here)*

</td>
</tr>
</table>

### How They Work

**Forge mode** (*Judicial AI*) — You say "Help me plan my thesis." The AI presents the case FOR and AGAINST your angle in parallel, then asks *"What's your central claim? What would someone who disagrees say?"* It never converges to a single recommendation (OMA principle: Open, Multiple, Adjunct).

**Anvil mode** (*Hounds protocol*) — You paste your draft. **The order matters**: you commit first (by submitting your full draft), the AI responds second. This is what Cabitza's 2023 study found preserved independent judgment. The AI rates on 6 dimensions, quotes the 3 weakest passages, and asks *"Where do you disagree with my assessment?"* It never rewrites.

**Crucible mode** (*Frictional AI*) — You bring **3+ ideas** (the mode refuses fewer). The AI steelmans each, attacks, and maps what you haven't considered. An epistemic-sclerosis guard kicks in if your ideas read as generic — the mode will ask for one wild or contrarian idea to stop premature convergence before pressure-testing.

**Executor mode** (*Rams protocol*) — Formatting, translation, boilerplate, scheduling. No friction, no questions. This is the only mode where the AI-first pattern is acceptable — Cabitza's research shows Rams causes anchoring when *judgment* is at stake, so the mode is instructed to warn you if it detects a thinking task here.

A fresh session starts in **Executor** mode. Friction is something you opt into, and it stays on until you switch out.

### Slash commands

| Command | What it does |
|---|---|
| `/forge-mode` | Switch to Forge — Socratic thinking partner |
| `/anvil-mode` | Switch to Anvil — rate and critique a draft you wrote |
| `/crucible-mode` | Switch to Crucible — stress-test 3+ ideas of your own |
| `/executor-mode` | Switch to Executor — normal AI, full tool access |
| `/forge-status` | Dashboard: active mode, message and violation counts, mode history, overdue audits |
| `/forge-audit [weekly\|monthly\|quarterly]` | Self-audit: weekly canary, monthly stress test, quarterly dependency review |

### Task detection

There is no separate classifier tool and no extra model call. `souls/forge-orchestrator.md` — injected once per session, in every mode — carries the thinking-vs-execution classifier and one instruction: if the session is in Executor mode and the request needs the user's judgment, name the mode that fits before doing the work, once, and then respect the answer. Each mode's slash-command and subagent `description` does the rest of the routing, where Claude Code already looks.

This layer is a prompt, so call it what it is: **a warning, not a lock.** The locks are in the [next section](#how-enforcement-works).

---

## Quick Start

### Prerequisites

- [Claude Code](https://claude.com/claude-code) — a working subscription is all the auth you need
- `python3` 3.11+ on `PATH` (the hook handlers run under the bare system interpreter, with **no** third-party packages)

That's the whole list. There is no `ANTHROPIC_API_KEY`, no `VERTEX_PROJECT`, no `pip install`.

### Install

From inside Claude Code:

```
/plugin marketplace add lorenzofamiglini/The-Forge-Protocol-Agent
/plugin install forge-protocol
```

Then:

```
/forge-mode
Help me think through my thesis on AI in education.
```

### Try it from a clone, without installing

```bash
git clone https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent.git
cd The-Forge-Protocol-Agent
claude --plugin-dir .
```

The plugin is loaded for that session only — nothing is copied anywhere, and edits to the working tree take effect on the next launch.

### For contributors

```bash
claude plugin validate --strict .        # manifest + agents + skills lint (CI-safe)
./bin/forge doctor                       # environment sanity check
python3 -m pytest                        # test suite (NOTE: bare `pytest` fails collection)
```

---

## How Enforcement Works

The Hermes original could only *ask* the model to stay in mode. Claude Code lets the harness enforce it, and that's the substantive upgrade. But the layers are not equally strong, so here is what each one actually guarantees.

| Hook | What it does |
|---|---|
| `SessionStart` | Announces the active mode, injects the orchestrator soul and that mode's system prompt, surfaces overdue audit reminders, and records which Forge session this working directory is using |
| `UserPromptSubmit` | Counts the turn, checks the mode's entry rules, delivers metacognitive checkpoints, and records mode changes **you** asked for |
| `PreToolUse` | **Denies `Write`, `Edit`, `MultiEdit`, `NotebookEdit`** — and `Bash` commands that write a file — while a thinking mode is active |
| `Stop` / `SubagentStop` | Runs the independent auditor over the finished response and blocks with the violation list when it finds one |
| `SessionEnd` | Surfaces the mode's closing reflection prompt |

### The write-lock, in three layers

While Forge, Anvil, or Crucible is active, a `PreToolUse` hook returns a hard `deny` for every write-capable tool, with a reason that quotes the mode rule being violated and logs a violation to the session file. This is deterministic and harness-run: it does not depend on the model's goodwill. "Never rewrites" and "never fills the gaps" stop being requests.

`Bash` cannot be denied outright — the slash-command skills need it to reach the `forge` CLI, which is how mode switching, status, and the canary work at all. So the hook inspects the command instead and denies the shell forms that write a file: output redirection to a real path, `tee`, `dd`, `truncate`, `install`, and in-place edits (`sed -i`, `perl -pi`). `>/dev/null` and read-only commands pass, so the CLI stays reachable.

That check is narrow on purpose and is **not** a sandbox. `python3 -c "open('f','w')..."` still gets through it. What catches that is the third layer: the independent output audit, which judges the response you actually produced — "I created the file for you" violates Forge's rules however the file got created. Deterministic denial for the ordinary paths, an LLM judge for the rest.

### A mode the model can leave is not a mode

The first live session test found the real hole, and it wasn't the shell. Denied the `Write` tool, the model invoked `/executor-mode` on its own authority, switched the session out of Forge mode, and wrote the file legally.

So `forge set-mode` now refuses to *leave* a thinking mode unless the user asked for it in their own words. `UserPromptSubmit` sees the raw prompt you submitted and records a mode request when it contains `/executor-mode`; `set-mode` consumes that record, single-use. Entering a thinking mode, or moving between two of them, needs no permission — **adding** friction is always allowed, only removing it is gated.

Run the same test now and the model reports back instead:

> The mode switch requires you to run it yourself — Forge Protocol won't let me leave Forge mode on my own authority. Please run `/executor-mode` to switch, then I'll create the file.

`forge set-mode <mode> --force` exists for humans driving the CLI directly outside a session. It works, and it logs a `mode:forced-relaxation` violation that shows up in `/forge-status` and in the quarterly dependency report — auditable rather than silent.

### Subagent tool lists are not the guarantee

`agents/forge.md`, `agents/anvil.md` and `agents/crucible.md` declare read-only `tools:` lists (`Read`, `Grep`, `Glob`). Those constrain a subagent the main session *explicitly delegates to* — nothing more. After `/forge-mode` you are still talking to the **main** agent, which retains its full tool set. The restricted lists are useful defense in depth for delegated work; the `PreToolUse` hook is the thing that actually holds the session.

### The output audit can block, and can't loop

When a thinking mode's turn ends, the `Stop` hook pulls the last assistant message out of the transcript and hands it to an independent auditor (see [below](#the-adversarial-auditor)). If the auditor finds violations, the hook blocks with the rule, the reason, and a verbatim quote, and the agent gets another turn to fix it. Three properties keep that from becoming a trap:

- It honors `stop_hook_active`, so a blocked turn is never re-blocked — the session cannot bounce between "revise" and "still not compliant" forever.
- An auditor failure never blocks anything. Any error — timeout, missing binary, unparseable reply — is treated as "no finding".
- `FORGE_OUTPUT_BLOCK=0` downgrades a finding from a block to a plain notification.

Every hook is wrapped so that an unexpected exception exits 0 with no output: a crashed hook would be worse than a skipped one, so Claude Code proceeds exactly as if the plugin were not installed. `FORGE_HOOK_DEBUG=1` prints the traceback instead of swallowing it.

### Executor mode has zero overhead, by design

No input audit, no output audit, no write-lock, no checkpoints, no reflection prompt — **zero per-turn cost**. Executor is the no-friction mode, and giving it nothing to pay for is a feature, not an oversight. Its one shared cost is the `SessionStart` context block every mode gets, which carries the orchestrator soul and the mode's own prompt.

---

## Configuration

Everything is an environment variable; the plugin manifest has no field for declaring them. All of them are optional.

| Variable | Default | Purpose |
|---|---|---|
| `FORGE_AUDITOR_ENABLED` | **enabled** | Set to `0`/`false`/`no`/`off` to turn the independent auditor off and fall back to model self-evaluation |
| `FORGE_AUDITOR_MODEL` | `sonnet` | Model for the output audit and canary scoring — a CLI alias or a full model id |
| `FORGE_AUDITOR_CMD` | `claude` | Path to the `claude` binary the auditor shells out to |
| `FORGE_AUDITOR_TIMEOUT` | `60` | Auditor subprocess timeout, in seconds |
| `FORGE_INPUT_BLOCK` | off | Set to `1` to make a failed entry-rule check block the prompt instead of annotating it |
| `FORGE_INPUT_AUDIT_ALWAYS` | off | Set to `1` to audit entry rules on every turn instead of only the first in a mode |
| `FORGE_INPUT_AUDITOR_MODEL` | `haiku` | Model for the cheap entry-rule check |
| `FORGE_OUTPUT_BLOCK` | on | Set to `0` to report output violations as a notification instead of blocking the turn |
| `FORGE_STATE_DIR` | `~/.forge-state` | Where session JSON and canary history live |
| `FORGE_MODES_DIR` | `<plugin>/modes` | Override the mode-definition directory |
| `FORGE_SESSION_ID` | resolved automatically | Pin the Forge session id (otherwise `SessionStart` records it and the CLI reads it back, keyed by working directory) |
| `FORGE_HOOK_DEBUG` | off | Set to `1` to print hook tracebacks to stderr instead of exiting silently |

One more is set by the plugin, not by you: `FORGE_AUDITOR_CHILD=1` marks the auditor's own `claude -p` child process so that every hook no-ops inside it. It is the second lock on the recursion guard, alongside `--safe-mode`. Don't set it in your shell — it disables the auditor.

**`./bin/forge doctor` is the troubleshooting entry point.** It prints the resolved plugin root, modes and souls directories, state directory, which modes loaded, whether PyYAML is present, which JSON twins exist, and the auditor's enabled/available/model/resolved-command state. If you are wondering why the auditor isn't running, that is the command that answers it.

### Why the entry-rule check doesn't run on every turn

Input rules are *entry* requirements — "submit your full draft", "bring at least 3 ideas of your own". They're about how you come into a mode, not about each individual message. One auditor judgment costs 6–9 seconds, and putting that in front of every prompt would tax the whole session for no extra safety, so by default the check runs on the first turn after you enter a thinking mode. Set `FORGE_INPUT_AUDIT_ALWAYS=1` to restore per-turn checking.

The entry check is also advisory by default: it annotates the turn with what's missing and tells the model to ask for it, rather than blocking the prompt. The **output** audit is the strict one — that's where rubber-stamping is the actual risk. `FORGE_INPUT_BLOCK=1` flips the input side to blocking too.

---

## Measure Your Cognitive Sovereignty

Most "anti-AI-dependency" tools are aspirational — they *tell* you to use AI less. Forge Protocol actually measures whether your independent skills are improving, flat, or drifting down.

### The adversarial auditor

The original design had one flaw: it asked the *same* LLM that generated a response to judge whether the response followed the mode rules. LLMs rubber-stamp themselves. Fixed:

- The `Stop` hook routes every thinking-mode response through an **independent Claude instance** that judges compliance, quotes violations verbatim, and returns structured JSON the hook treats as ground truth.
- That instance is a headless `claude -p` subprocess running against **your existing Claude Code credentials** — no API key, no cloud project, no `anthropic` SDK. It runs with `--safe-mode` (which disables plugins, hooks, skills and CLAUDE.md for the child, so the audit can't re-trigger Forge's own hooks and recurse), `--tools ""` (a judge, not an agent), and `--json-schema` (server-side structured output).
- Because it needs nothing you don't already have, it is **on by default**. `FORGE_AUDITOR_ENABLED=0` turns it off; if `claude` isn't resolvable, the hooks fall back to handing the rules to the model for self-evaluation instead of failing.
- Run the auditor and your primary session on different models if you like — `FORGE_AUDITOR_MODEL` is independent of whatever model you're chatting with.

**What it costs.** One audit takes roughly **6–9 seconds** of wall time and consumes **Claude Code usage limits, not dollars**. There is no per-call bill on a subscription. (The CLI reports a `total_cost_usd` figure; that's list-price accounting for the tokens, not a charge.) The audit fires once per thinking-mode turn, and never in Executor mode.

### The canary — real skill tracking, not reminders

A fixed set of prompts (writing, analysis, debugging, strategy, communication) with stable IDs. You answer one unassisted, the auditor scores it, and the result is stored across weeks so you can see the trend.

```
/forge-audit weekly
# → one prompt shown, with its time limit (on your honor — a skill can't run a timer)
# → you submit your unassisted answer in the next turn
# → auditor returns:
  clarity: 4    depth: 3    independence: 5     overall: 4.0
  change vs. previous: +0.3   mean of last 5: 3.8   slope: +0.15/attempt
```

If the slope is flat or negative after a few weeks, the framework is failing you — and you'll hear that honestly instead of a "great job!" from a sycophantic model.

| What it tracks | What the number means |
|---|---|
| **Clarity** (1-5) | Specific, readable, no filler hedging |
| **Depth** (1-5) | Genuine reasoning, not templated surface |
| **Independence** (1-5) | Your voice, not pasted AI patterns |
| **Slope per attempt** | Linear trend across your full canary history |

Storage lives at `~/.forge-state/canary_history.json` (deliberately separate from the per-session files). Nothing leaves your machine except the single auditor call that returns a score.

---

## For Schools & Universities

Forge Protocol was built with education in mind. It turns Claude Code into a **Socratic tutor** that strengthens student thinking instead of replacing it.

### The Problem in Education
- Students paste assignments into an AI chat and submit the output
- Writing skills decline because the AI writes for them
- Critical thinking atrophies because the AI thinks for them
- Students can't tell the difference between understanding and having access to answers

### How Forge Protocol Helps

| Without Forge | With Forge |
|---------------|------------|
| Student: "Write my essay on climate policy" | Student: "Write my essay on climate policy" |
| AI: *writes a complete essay* | AI: *"What's your thesis? What evidence supports it? What's the strongest counterargument?"* |
| Student learns: nothing | Student learns: how to build an argument |

### Deployment Options

1. **Individual students** — `/plugin install forge-protocol` on their own machine, used for study sessions and paper writing
2. **Course-level** — Instructor publishes the marketplace entry (or a fork with course-specific modes); students add it and work in Forge mode
3. **Institution-level** — Ship it in a managed Claude Code configuration, with `FORGE_INPUT_BLOCK=1` and `FORGE_OUTPUT_BLOCK=1` for strict enforcement on academic work
4. **Research** — Use the audit system and the JSON state files to measure skill progression over time

### Self-Audit System

The **measurable** part of the framework — see [Measure Your Cognitive Sovereignty](#measure-your-cognitive-sovereignty) above for the full write-up. Three cadences:
- **Weekly canary** — Unassisted challenge on a stable prompt. Auditor scores it on clarity, depth, and independence. Compared across weeks.
- **Monthly stress test** — Extended unassisted work. Compared to your AI-assisted baseline.
- **Quarterly dependency audit** — Mode usage analysis. Catches "living in Executor mode."

---

## Architecture

Four layers, deliberately separated.

| Layer | What lives there | Rule |
|---|---|---|
| **Portable core** | `lib/` — mode loading, session state, validation rules, canary, checkpoints, audit reports, the auditor | Zero host dependency. No import of `forge_cc/`, no knowledge of Claude Code. Usable from any Python project |
| **Host integration** | `forge_cc/` — hook policy, the `forge` CLI, path/session/state resolution, transcript reading, hook wire format | The only Claude-Code-aware Python in the repo |
| **Prompt layer** | `modes/*.yaml` (machine-readable rules) + `souls/*.md` (the orchestrator soul plus one per mode) + `agents/*.md` (subagents) + `skills/*/SKILL.md` (slash commands) | Rules drive the auditor; souls and agents drive generation |
| **Wiring** | `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `hooks/hooks.json`, `hooks-handlers/*.py`, `bin/forge` | Discovered by convention; handlers are thin shims over `forge_cc.handlers` |

```
You, in Claude Code
  |
  |-- SessionStart ........ inject the orchestrator soul + the active mode's
  |                         soul + any overdue audit reminders
  |
  |-- /forge-mode ......... skill shells out to `bin/forge set-mode forge`
  |
  |-- UserPromptSubmit .... count the turn
  |                         check the mode's entry rules (first turn in mode)
  |                         deliver a metacognitive checkpoint when due
  |
  |-- [ the model answers, optionally delegating to a mode subagent ]
  |
  |-- PreToolUse .......... deny Write / Edit / MultiEdit / NotebookEdit
  |                         while forge | anvil | crucible is active
  |
  |-- Stop / SubagentStop . independent `claude -p` auditor judges the response
  |                         block with the violation list, or pass
  |
  v
Response -> You            (SessionEnd: the mode's reflection prompt)
```

### Project Structure

```
forge-protocol/
├── .claude-plugin/
│   ├── plugin.json      # plugin manifest
│   └── marketplace.json # so users can `/plugin marketplace add <repo>`
├── hooks/
│   └── hooks.json       # 6 hook registrations, ${CLAUDE_PLUGIN_ROOT}-relative
├── hooks-handlers/      # one python3 shim per event
│   ├── session-start.py
│   ├── user-prompt-submit.py
│   ├── pre-tool-use.py
│   ├── stop.py
│   ├── subagent-stop.py
│   └── session-end.py
├── forge_cc/            # the only Claude-Code-aware Python
│   ├── handlers.py      # hook policy: write-lock, audits, checkpoints
│   ├── cli.py           # the `forge` CLI the skills shell out to
│   ├── hookio.py        # stdin/stdout wire format; never crashes a session
│   ├── paths.py         # plugin root, state dir, session pointer
│   └── transcript.py    # read the last assistant message for the audit
├── bin/
│   └── forge            # CLI entry point
├── lib/                 # pure Python core (no host dependency)
│   ├── modes.py         # mode loader (YAML, with JSON fallback)
│   ├── state.py         # session state management
│   ├── validator.py     # rule retrieval for LLM evaluation
│   ├── auditor.py       # adversarial auditor over headless `claude -p`
│   ├── canary.py        # fixed canary prompts + skill tracking
│   ├── checkpoints.py   # metacognitive checkpoint scheduler
│   └── audit.py         # weekly/monthly/quarterly audits + dependency report
├── modes/               # portable mode definitions
│   ├── forge.yaml       #   ... authored format
│   ├── forge.json       #   ... committed twin, for hosts without PyYAML
│   ├── anvil.yaml / .json
│   ├── crucible.yaml / .json
│   ├── executor.yaml / .json
│   └── schema.yaml      # field reference (not runtime-validated)
├── agents/              # subagents: forge, anvil, crucible, executor
├── souls/               # system prompts
│   ├── forge-orchestrator.md  # classifier + enforcement notice, every session
│   └── forge.md / anvil.md / crucible.md / executor.md
├── skills/              # slash commands (/forge-mode, /forge-audit, ...)
├── scripts/
│   └── build_modes_json.py  # regenerate the JSON twins after editing YAML
├── docs/                # research paper (LaTeX source)
├── tests/               # unit tests (pytest)
└── RESEARCH.md          # theoretical grounding + citations
```

### Key Design Choices

- **No API key** — The auditor is a headless `claude -p` subprocess on your existing credentials. A Claude Code subscription is the whole dependency list.
- **No pip dependencies at runtime** — Hook handlers run under the bare system `python3`, and a Claude Code plugin cannot declare pip requirements. Each `modes/*.yaml` therefore has a committed `modes/*.json` twin that `lib/modes.py` falls back to when PyYAML is absent.
- **Portable core** — `lib/` has zero host dependency. Use it in any Python project.
- **YAML-driven modes** — Add custom modes by dropping a YAML file (plus a soul, a subagent, a skill, and a regenerated JSON twin).
- **File-based state** — JSON session files under `~/.forge-state/`. No database required.
- **Enforcement is LLM-native, never regex** — `lib/validator.py` returns the mode's natural-language rules; an independent model judges compliance against them.

---

## Create Your Own Mode

Drop a YAML file in `modes/`:

```yaml
id: mentor
name: "Mentor Mode"
description: "Guides through problems step by step, never gives the answer"

system_prompt_file: "souls/mentor.md"

behaviors:
  required:
    - "Break problems into sub-problems"
    - "Ask the student to solve each sub-problem"
    - "Every response must contain at least one question"
  forbidden:
    - "Give the final answer directly"
    - "Skip steps in the reasoning"

input_rules:
  - "Student must attempt the problem before receiving guidance"

metacognitive:
  checkpoint_interval: 3
  prompts:
    - "Can you explain what we've figured out so far in your own words?"
```

Then add `souls/mentor.md` (the system prompt), and run:

```bash
python3 scripts/build_modes_json.py    # regenerate the JSON twins — never hand-edit them
```

For a first-class mode with its own slash command, subagent, and write-lock treatment, see the checklist in [CLAUDE.md](CLAUDE.md#adding-a-mode).

---

## The Research

Forge Protocol is grounded in peer-reviewed cognitive science and the Cabitza lab's decade-long empirical programme on human-AI collaboration. [RESEARCH.md](RESEARCH.md) has the full mapping; the summary:

**Foundational cognitive science:**
- **Generation effect** (Slamecka & Graf, 1978) — self-generated content is retained better than passively consumed content
- **Desirable difficulties** (Bjork & Bjork, 1994) — productive struggle improves long-term retention
- **Cognitive forcing strategies** (Croskerry, 2003) — explicit commitment before consultation activates analytical reasoning
- **Automation complacency** (Parasuraman & Manzey, 2010) — humans stop verifying automated output after initial trust

**Cabitza lab — empirical human-AI collaboration protocols (Milano-Bicocca):**
- **Hounds / Rams / White Boxes** (Cabitza et al., 2023, *Artificial Intelligence in Medicine*) — human-first ordering empirically preserves judgment; AI-first collapses it
- **White-box paradox** (Cabitza et al., 2024 — xAI 2024 Best Paper) — articulate explanations increase automation bias rather than decrease it
- **Frictional AI + programmed inefficiencies** (Cabitza et al., 2019, 2024) — deliberate cognitive challenges prevent automatic reliance
- **Judicial AI paradigm** (Cabitza et al., 2025) — contrasting evidence replaces oracular verdicts
- **OMA — Open, Multiple, Adjunct** (Cabitza et al., 2022) — design principles for decision-support outputs
- **Displacement protocol** (Cabitza et al., 2025 — *Five Degrees of Separation*) — 87–89% accuracy when human and AI work independently then combine
- **Deskilling taxonomy** (Natali, Marconi, Dias Duran, Miglioretti & Cabitza, 2025) — four types: cognitive, semiotic, social, moral + epistemic sclerosis at team level

**Famiglini lab contributions (maintainer's own co-authored work):**
- **Pro-hoc explanations** (Famiglini et al., 2024, *Never tell me the odds*, AI in Medicine Vol 150) — commitments before explanations prevent anchoring
- **Contrasting evidence via CAMs** (Famiglini et al., CD-MAKE 2022; 2024 alternative strategies) — visual dual-evidence forces active adjudication
- **Evidence-based XAI design** — explanations evaluated on understandability + clinical relevance, not plausibility
- **Conformal prediction for ECG** (Famiglini et al., 2025) — uncertainty quantification as commitment-forcing mechanism

**Convergence and the Wharton RCT:**
- **AI-induced convergence** (Doshi & Hauser, 2024) — 5% homogenisation across AI-assisted creative outputs
- **AI-induced skill decline** (Dell'Acqua et al., 2024) — 17% unassisted-performance decline after one week of AI use

---

## Built On

Forge Protocol is a native [**Claude Code**](https://claude.com/claude-code) plugin. It uses Claude Code's own primitives rather than any bespoke runtime: a plugin manifest and marketplace entry, `hooks/hooks.json` for harness-level enforcement, `agents/` for mode subagents, and `skills/` for slash commands. `${CLAUDE_PLUGIN_ROOT}` is how the hook commands find their handlers, and the adversarial auditor is a headless `claude -p` subprocess on the credentials Claude Code already holds.

### Attribution

This is the **Claude Code port** of Forge Protocol. The original project was created by **Lorenzo Famiglini** as a plugin for [Hermes Agent](https://github.com/NousResearch/hermes-agent) (Nous Research), and lives at [**lorenzofamiglini/The-Forge-Protocol-Agent**](https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent). The four-mode design, the mode definitions, the souls, the canary system, and the research grounding are all his; this port replaces the Hermes plugin layer with Claude Code hooks, subagents, and skills, and removes the API-key dependency. Distributed under the same MIT license — see [LICENSE](LICENSE).

Thanks also to the Nous Research team, whose Hermes Agent was the foundation the original was built on.

---

## Contributing

Forge Protocol is open source (MIT). We welcome:

- **New modes** — Custom YAML mode definitions for specific domains (law, medicine, coding)
- **Adapters** — Integrations with Cursor, Aider, VS Code, or other AI tools
- **Research** — Studies measuring the effectiveness of cognitive forcing functions
- **Translations** — Internationalize the system prompts and mode definitions

Run `claude plugin validate --strict .` and `python3 -m pytest` before opening a PR. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines and [CLAUDE.md](CLAUDE.md) for the architecture notes.

---

## FAQ

**Q: Doesn't this just make AI slower and more annoying?**
A: In Forge/Anvil/Crucible modes, yes — intentionally. That friction is the feature. When you need speed, switch to Executor mode, which has no friction and no overhead at all. The protocol distinguishes between tasks that need your brain and tasks that don't.

**Q: Do I need an API key?**
A: No. That's the point of this port. The auditor runs as a headless `claude -p` subprocess against the credentials Claude Code already has. `ANTHROPIC_API_KEY`, `VERTEX_PROJECT`, and the `anthropic` SDK appear nowhere in the tree.

**Q: Does the auditor cost money?**
A: Not on a subscription. It consumes Claude Code usage limits — roughly 6–9 seconds and one short model call per thinking-mode turn. The `total_cost_usd` number the CLI reports is list-price token accounting, not a bill.

**Q: Can the AI still write files while I'm in a thinking mode?**
A: The ordinary path is blocked: a `PreToolUse` hook hard-denies `Write`, `Edit`, `MultiEdit` and `NotebookEdit`. `Bash` is not blocked, because the slash commands need it to reach the `forge` CLI — so a determined model could still write through a shell redirect. It's a guardrail, not a sandbox, and we'd rather say so than oversell it.

**Q: Can I use this without Claude Code?**
A: Partly. The `lib/` directory is a standalone Python library with no runtime dependencies (PyYAML is optional — the committed `modes/*.json` twins cover its absence). Import `get_input_rules()` and `get_output_rules()` to retrieve the natural-language rules for a mode, then have your own LLM evaluate compliance. The prompt files in `souls/` can be pasted into any LLM's system prompt. The enforcement layer, though, is Claude Code hooks.

**Q: Is this just a system prompt?**
A: The system prompts (`souls/`, `agents/`) are the starting point, but Forge Protocol adds enforcement the model doesn't get a vote on: a harness-level write-lock, an independent auditor that can send a non-compliant response back for revision, entry-rule checks, metacognitive checkpoints, and a self-audit system that measures whether your unassisted skills are actually holding. All judgment is LLM-native — natural-language rules evaluated by an independent model, not regex.

---

<div align="center">

**Stop outsourcing your thinking.**

[Get Started](#quick-start) | [Star this repo](https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent)

---

## Author

Created by **Lorenzo Famiglini, PhD** (lorenzofamiglini@gmail.com). Co-author on the Cabitza lab's work on explainable AI in medical decision support, contrasting-evidence class-activation-maps (CD-MAKE 2022; 2024), *Never tell me the odds* (AI in Medicine 2024), and conformal prediction for ECG interpretation (2025). Forge Protocol is a direct implementation of those collaboration protocols, translated from medical decision support to LLM-augmented knowledge work.

Claude Code port of the original [Hermes Agent plugin](https://github.com/lorenzofamiglini/The-Forge-Protocol-Agent), MIT licensed.

</div>

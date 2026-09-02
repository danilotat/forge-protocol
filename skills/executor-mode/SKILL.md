---
name: executor-mode
description: Switch to Executor mode — normal, friction-free AI operation with full tool access, for mechanical tasks only. Use when the user invokes executor-mode ($executor-mode in Codex, /executor-mode in Claude Code), says "just do it", or needs work where their own judgment is not at stake.
---

# Executor Mode — Standard AI Operation

Switch to Executor mode for **mechanical tasks** that don't require your judgment.

## When to Use

- Formatting, translation, data transformation
- Boilerplate code generation
- Calendar coordination, scheduling
- Summarizing documents you've already read
- Any task where delegation is appropriate

## How It Works

Executor mode is standard AI behavior — no friction, no questioning, no checkpoints. The AI does exactly what you ask.

## Activation

**The switch has already happened.** The `UserPromptSubmit` hook reads the user's own prompt, applies the mode change itself, and injects the new mode's rules into your context — so there is nothing to run here. Do **not** call `forge set-mode`; it would be a redundant shell round-trip and its JSON would be rendered to the user for no reason. If you need the current state for some other purpose, the `forge` CLI is at the absolute path given as `FORGE_CLI:` in the session context.

1. **Report the switch in one line, no ceremony** — "Executor mode: full tool access, no friction. What do you need?" — and get on with the task. This is the one mode where the AI-first pattern is sanctioned, so don't manufacture questions or checkpoints.

3. **Delegate to the `executor` subagent** for a bounded mechanical task, or just do the work directly. The `executor` subagent has the default full tool set, and the `PreToolUse` write-lock that guards Forge, Anvil, and Crucible does not apply here — `Write`, `Edit`, `MultiEdit`, and `NotebookEdit` are all available.

## When NOT to Use

If the user's request is a **thinking task** — an email in their voice, an argument, a design choice, a strategy call — say so before executing it, in one sentence, and name the skill that fits (`forge-mode`, `anvil-mode`, or `crucible-mode`). Then do as they ask if they confirm. The warning is the whole safeguard here: Executor mode has no other friction, so an unflagged thinking task delegated in Executor mode is exactly the deskilling path the protocol exists to interrupt.

## Rules

- No input requirements
- No output restrictions
- No metacognitive checkpoints
- Full automation — the AI writes, generates, formats freely

## Research basis

Executor mode is the only context where the **Rams (AI-first) protocol** from Cabitza et al. (2023) is acceptable. Rams causes anchoring and automation bias when judgment is involved — for mechanical tasks those biases are irrelevant because there's no judgment to corrupt. If you catch yourself using Executor for a task that carries your voice (an email, an argument, a design choice), switch modes. Full derivation in [RESEARCH.md](../../RESEARCH.md).

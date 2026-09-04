---
name: executor-mode
description: Switch to Executor mode — normal, friction-free AI operation with full tool access, for mechanical tasks only. Use only when the user explicitly invokes executor-mode ($executor-mode in Codex, /executor-mode in Claude Code); semantic matching must never relax a thinking mode.
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

Executor activation is user-controlled. Use this skill only when `UserPromptSubmit` says the user selected Executor; the hook has already set source `user` and injected the Executor soul. Do not run `forge set-mode` or `forge route-mode`. If this skill was selected only because a task looks mechanical while a thinking mode is active, stop and ask the user to invoke `executor-mode` themselves.

1. **Report the switch in one line, no ceremony** — "Executor mode: full tool access, no friction. What do you need?" — and get on with the task. This is the one mode where the AI-first pattern is sanctioned, so don't manufacture questions or checkpoints.

2. **Do the work directly** in the main agent. An `executor` subagent is optional when the host exposes one. The `PreToolUse` write-lock that guards Forge, Anvil, and Crucible does not apply here — `Write`, `Edit`, `MultiEdit`, and `NotebookEdit` are all available.

## When NOT to Use

If the user's request is a **thinking task** — an email in their voice, an argument, a design choice, a strategy call — say so before executing it, in one sentence, and name the skill that fits (`forge-mode`, `anvil-mode`, or `crucible-mode`). Then do as they ask if they confirm. The warning is the whole safeguard here: Executor mode has no other friction, so an unflagged thinking task delegated in Executor mode is exactly the deskilling path the protocol exists to interrupt.

## Rules

- No input requirements
- No output restrictions
- No metacognitive checkpoints
- Full automation — the AI writes, generates, formats freely

## Research basis

Executor mode is the only context where the **Rams (AI-first) protocol** from Cabitza et al. (2023) is acceptable. Rams causes anchoring and automation bias when judgment is involved — for mechanical tasks those biases are irrelevant because there's no judgment to corrupt. If you catch yourself using Executor for a task that carries your voice (an email, an argument, a design choice), switch modes. Full derivation in [RESEARCH.md](../../RESEARCH.md).

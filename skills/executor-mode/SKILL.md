---
name: executor-mode
description: Switch to Executor mode — normal, friction-free AI operation with full tool access, for mechanical tasks only. Use when the user runs /executor-mode or says "just do it", "stop asking questions", "no friction", or needs formatting, translation, boilerplate, data transformation, or scheduling where their own judgment is not at stake.
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

Run the `forge` CLI at the absolute path given as `FORGE_CLI:` in the Forge Protocol session context; if that line is absent, fall back to `${CLAUDE_PLUGIN_ROOT}/bin/forge`. Commands below write that path as `<FORGE_CLI>`.

1. **Switch the session mode:**

   ```bash
   <FORGE_CLI> set-mode executor
   ```

   The JSON reply carries `previous`, `current`, `changed`, `description`, and `message` (and `write_tools_blocked: false`, since this mode has no write-lock). If `changed` is `false` the session was already in Executor mode; say that instead of announcing a switch.

2. **Report the switch in one line, no ceremony** — "Executor mode: full tool access, no friction. What do you need?" — and get on with the task. This is the one mode where the AI-first pattern is sanctioned, so don't manufacture questions or checkpoints.

3. **Delegate to the `executor` subagent** for a bounded mechanical task, or just do the work directly. The `executor` subagent has the default full tool set, and the `PreToolUse` write-lock that guards Forge, Anvil, and Crucible does not apply here — `Write`, `Edit`, `MultiEdit`, and `NotebookEdit` are all available.

## When NOT to Use

If the user's request is a **thinking task** — an email in their voice, an argument, a design choice, a strategy call — say so before executing it, in one sentence, and name the mode that fits (`/forge-mode`, `/anvil-mode`, `/crucible-mode`). Then do as they ask if they confirm. The warning is the whole safeguard here: Executor mode has no other friction, so an unflagged thinking task delegated in Executor mode is exactly the deskilling path the protocol exists to interrupt.

## Rules

- No input requirements
- No output restrictions
- No metacognitive checkpoints
- Full automation — the AI writes, generates, formats freely

## Research basis

Executor mode is the only context where the **Rams (AI-first) protocol** from Cabitza et al. (2023) is acceptable. Rams causes anchoring and automation bias when judgment is involved — for mechanical tasks those biases are irrelevant because there's no judgment to corrupt. If you catch yourself using Executor for a task that carries your voice (an email, an argument, a design choice), switch modes. Full derivation in [RESEARCH.md](../../RESEARCH.md).

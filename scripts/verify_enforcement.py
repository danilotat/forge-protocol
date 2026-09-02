#!/usr/bin/env python3
"""End-to-end check that the mode boundaries are actually enforced.

The unit tests call the handler functions directly. This script goes through
the real wire instead: it spawns the hook shims as subprocesses the way Claude
Code does, feeds them JSON on stdin, and asserts on what comes back on stdout.
That is the only way to catch a broken shim, a bad sys.path bootstrap, or a
hooks.json path that does not resolve.

    python3 scripts/verify_enforcement.py          # offline, uses a fake auditor
    python3 scripts/verify_enforcement.py --live   # also makes one real audit call

`--live` spends one real Claude Code model call (~6-9s, subscription usage,
no API key) and is the acceptance test for the whole point of this port.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOKS = REPO / "hooks-handlers"
FORGE = REPO / "bin" / "forge"

_passed = 0
_failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed
    if condition:
        _passed += 1
        print(f"  ok   {name}")
    else:
        _failed.append(name)
        print(f"  FAIL {name}" + (f"\n       {detail}" if detail else ""))


def hook(event_script: str, payload: dict, env: dict | None = None) -> dict:
    """Run a hook shim exactly as Claude Code would and parse its output."""
    proc = subprocess.run(
        [sys.executable, str(HOOKS / event_script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    if proc.returncode != 0:
        raise AssertionError(
            f"{event_script} exited {proc.returncode}: {proc.stderr[:400]}"
        )
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def set_mode(mode: str) -> dict:
    """Switch modes for setup. --force because leaving a thinking mode now
    requires a user request, and this script is the user."""
    return forge("set-mode", mode, "--force")


def forge(*args: str, env: dict | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(FORGE), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def write_transcript(path: Path, assistant_text: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "q"}}) + "\n")
        f.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "thinking", "thinking": "must not be audited"},
                            {"type": "text", "text": assistant_text},
                        ],
                    },
                }
            )
            + "\n"
        )


def fake_auditor(tmp: Path, *, violations: bool) -> Path:
    """A stand-in `claude` binary that records its argv and returns a verdict."""
    payload = {
        "is_error": False,
        "subtype": "success",
        "result": "{}",
        "structured_output": {
            "compliant": not violations,
            "violations": (
                [
                    {
                        "rule": "Offer single authoritative recommendation (oracular mode)",
                        "kind": "forbidden",
                        "quote": "You should use Postgres.",
                        "reason": "Converges on one option.",
                    }
                ]
                if violations
                else []
            ),
        },
    }
    script = tmp / "fake-claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"open({str(tmp / 'argv.json')!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"print({json.dumps(json.dumps(payload))})\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="also run one real audit through the claude CLI",
    )
    args = parser.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="forge-verify-"))
    state = tmp / "state"
    base = {
        "FORGE_STATE_DIR": str(state),
        "FORGE_AUDITOR_ENABLED": "0",
        "FORGE_HOOK_DEBUG": "1",
    }
    os.environ.update(base)
    # Prove the port's premise: nothing here reads an API key.
    for leftover in ("ANTHROPIC_API_KEY", "VERTEX_PROJECT", "VERTEX_REGION"):
        os.environ.pop(leftover, None)

    sid = "verify-session"
    cwd = str(REPO)
    payload = {"session_id": sid, "cwd": cwd}

    print("\nno API key in the environment")
    check(
        "ANTHROPIC_API_KEY unset",
        "ANTHROPIC_API_KEY" not in os.environ,
    )
    check(
        "anthropic SDK not imported anywhere in the tree",
        not subprocess.run(
            ["grep", "-rn", "--include=*.py", "-e", "^import anthropic",
             "-e", "^from anthropic", str(REPO / "lib"), str(REPO / "forge_cc")],
            capture_output=True,
            text=True,
            check=False,
        ).stdout,
    )

    print("\nSessionStart")
    out = hook("session-start.py", {**payload, "source": "startup"})
    context = out.get("hookSpecificOutput", {}).get("additionalContext", "")
    check("injects context", bool(context))
    check("names the active mode", "Executor Mode" in context)
    check("publishes FORGE_CLI path", "FORGE_CLI:" in context and str(FORGE) in context)
    check(
        "records the session pointer",
        forge("state").get("session_id") == sid,
        f"got {forge('state').get('session_id')!r}",
    )

    print("\nPreToolUse write-lock")
    for mode in ("forge", "anvil", "crucible"):
        set_mode(mode)
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            out = hook("pre-tool-use.py", {**payload, "tool_name": tool, "tool_input": {}})
            decision = out.get("hookSpecificOutput", {}).get("permissionDecision")
            check(f"{mode}: {tool} denied", decision == "deny", f"got {decision!r}")
        for tool in ("Read", "Grep", "Bash"):
            out = hook("pre-tool-use.py", {**payload, "tool_name": tool, "tool_input": {}})
            check(f"{mode}: {tool} allowed", out == {}, f"got {out!r}")

    set_mode("executor")
    for tool in ("Write", "Edit"):
        out = hook("pre-tool-use.py", {**payload, "tool_name": tool, "tool_input": {}})
        check(f"executor: {tool} allowed", out == {}, f"got {out!r}")

    print("\nviolation logging")
    set_mode("forge")
    before = forge("state").get("violation_count", 0)
    hook("pre-tool-use.py", {**payload, "tool_name": "Write", "tool_input": {}})
    check(
        "denial is recorded in session state",
        forge("state").get("violation_count", 0) == before + 1,
    )

    print("\nUserPromptSubmit")
    set_mode("forge")
    start = forge("state")["message_count"]
    hook("user-prompt-submit.py", {**payload, "prompt": "my position is X because Y"})
    check(
        "counts exactly one message per turn",
        forge("state")["message_count"] == start + 1,
    )

    fired = []
    for _ in range(6):
        out = hook("user-prompt-submit.py", {**payload, "prompt": "my reasoning is X"})
        ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
        fired.append("checkpoint is due" in ctx)
    check("metacognitive checkpoint fires on interval", any(fired))
    check("checkpoint does not fire every turn", not all(fired))

    set_mode("executor")
    out = hook("user-prompt-submit.py", {**payload, "prompt": "reformat this csv"})
    check("executor mode adds zero friction", out == {}, f"got {out!r}")

    print("\nmode-relaxation consent gate")
    set_mode("forge")
    denied = forge("set-mode", "executor")
    check(
        "model cannot leave a thinking mode on its own",
        "error" in denied and "refusing to leave" in denied["error"],
        f"got {denied!r}",
    )
    check("mode is unchanged after the refusal", forge("state")["current_mode"] == "forge")
    hook("user-prompt-submit.py", {**payload, "prompt": "/executor-mode"})
    allowed = forge("set-mode", "executor")
    check(
        "the user's own /executor-mode is honored",
        allowed.get("current") == "executor",
        f"got {allowed!r}",
    )

    print("\nStop hook, fake auditor")
    set_mode("forge")
    transcript = tmp / "transcript.jsonl"
    write_transcript(transcript, "You should use Postgres.")
    audit_env = {
        "FORGE_AUDITOR_ENABLED": "1",
        "FORGE_AUDITOR_CMD": str(fake_auditor(tmp, violations=True)),
    }
    stop_payload = {**payload, "transcript_path": str(transcript), "stop_hook_active": False}

    out = hook("stop.py", stop_payload, env=audit_env)
    check("blocks a non-compliant response", out.get("decision") == "block", f"got {out!r}")
    check("block reason lists the violation", "oracular" in out.get("reason", ""))

    out = hook("stop.py", {**stop_payload, "stop_hook_active": True}, env=audit_env)
    check("honors stop_hook_active (no infinite loop)", out == {}, f"got {out!r}")

    argv = json.loads((tmp / "argv.json").read_text())
    check("auditor runs in print mode", "-p" in argv)
    check("auditor passes --safe-mode (recursion guard)", "--safe-mode" in argv)
    check("auditor disables all tools", "--tools" in argv and argv[argv.index("--tools") + 1] == "")
    check("auditor requests structured output", "--json-schema" in argv)
    # --bare would force ANTHROPIC_API_KEY / apiKeyHelper auth and never read
    # the user's OAuth credentials, defeating the entire point of this port.
    check("auditor never passes --bare", "--bare" not in argv)

    out = hook("stop.py", stop_payload, env={**audit_env, "FORGE_AUDITOR_CHILD": "1"})
    check("recursion guard suppresses the hook", out == {}, f"got {out!r}")

    compliant_env = {
        "FORGE_AUDITOR_ENABLED": "1",
        "FORGE_AUDITOR_CMD": str(fake_auditor(tmp, violations=False)),
    }
    out = hook("stop.py", stop_payload, env=compliant_env)
    check("compliant response passes through", out == {}, f"got {out!r}")

    broken = tmp / "broken-claude"
    broken.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    broken.chmod(0o755)
    out = hook(
        "stop.py",
        stop_payload,
        env={"FORGE_AUDITOR_ENABLED": "1", "FORGE_AUDITOR_CMD": str(broken)},
    )
    check("a failing auditor never blocks the response", out == {}, f"got {out!r}")

    set_mode("executor")
    out = hook("stop.py", stop_payload, env=audit_env)
    check("executor mode is never audited", out == {}, f"got {out!r}")

    print("\nSessionEnd")
    set_mode("forge")
    out = hook("session-end.py", {**payload, "reason": "clear"})
    check("surfaces the closing reflection prompt", "systemMessage" in out, f"got {out!r}")

    if args.live:
        print("\nlive audit through the real claude CLI (no API key)")
        if not shutil.which("claude"):
            check("claude on PATH", False, "claude binary not found")
        else:
            set_mode("forge")
            write_transcript(
                transcript,
                "Here's what I'd suggest: split the monolith into three services now.",
            )
            out = hook("stop.py", stop_payload, env={"FORGE_AUDITOR_ENABLED": "1"})
            check(
                "real auditor blocks an oracular response",
                out.get("decision") == "block",
                f"got {out!r}",
            )
            check(
                "verdict cites concrete rules",
                "forbidden" in out.get("reason", "") or "required_missing" in out.get("reason", ""),
            )

    shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{_passed} passed, {len(_failed)} failed")
    if _failed:
        for name in _failed:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run one output audit out of band, after the Stop hook has already returned.

In the default (non-blocking) path the auditor's verdict is not needed until
the user's next turn, so making the Stop hook wait ~4s for it buys nothing but
latency. The hook spawns this worker detached and returns immediately; the
worker does the audit and drops the finding in the pending-audit slot, where
`UserPromptSubmit` picks it up.

Reads one JSON object on stdin:

    {"mode": "forge", "response": "...", "user_message": "...", "cwd": "..."}

Writes nothing to stdout. Never raises out of `main` — a failed background
audit must be indistinguishable from no audit.
"""

from __future__ import annotations

import json
import sys

from .paths import clear_audit_inflight, ensure_importable, set_pending_audit

ensure_importable()

from lib import auditor  # noqa: E402
from lib.modes import load_all_modes  # noqa: E402
from lib.validator import get_output_rules  # noqa: E402


def _log(message: str) -> None:
    """Progress breadcrumbs for debugging a detached worker (opt-in)."""
    import os

    if not os.environ.get("FORGE_HOOK_DEBUG"):
        return
    try:
        from .paths import state_dir

        target = state_dir() / "audit" / "worker.log"
        target.parent.mkdir(parents=True, exist_ok=True)
        import time as _t

        with open(target, "a", encoding="utf-8") as f:
            f.write(f"{_t.time():.3f} {message}\n")
    except Exception:  # noqa: BLE001
        pass


def run(payload: dict) -> None:
    from .paths import modes_dir

    cwd = payload.get("cwd")
    _log("worker start")
    try:
        mode_id = payload.get("mode") or ""
        response = payload.get("response") or ""
        if not mode_id or not response:
            return

        modes = load_all_modes(modes_dir())
        mode = modes.get(mode_id)
        if mode is None:
            return

        _log("calling auditor")
        audit = auditor.audit_output(
            response,
            get_output_rules(mode),
            user_message=payload.get("user_message") or "",
        )
        _log(f"auditor returned: error={audit.error if audit else 'None'} "
             f"violations={len(audit.violations) if audit else 0}")
        if audit is None or audit.error or audit.compliant or not audit.violations:
            return

        lines = []
        for v in audit.violations:
            detail = f"  - [{v.kind}] {v.rule}"
            if v.reason:
                detail += f"\n    why: {v.reason}"
            if v.quote:
                detail += f'\n    quote: "{v.quote}"'
            lines.append(detail)

        set_pending_audit(
            f"Forge Protocol — an independent auditor ({audit.auditor_model}) found "
            f"your previous response violated {mode.name}:\n\n" + "\n".join(lines),
            cwd,
        )
        _log("finding stored")
    finally:
        clear_audit_inflight(cwd)
        _log("worker done")


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        if isinstance(payload, dict):
            run(payload)
    except BaseException:  # noqa: BLE001 — a background audit never complains
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Path, state-dir, and session-pointer resolution for the Claude Code port.

This is the only place that knows where things live. `lib/` stays a pure
portable core with no knowledge of Claude Code; everything host-specific
lands here.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

#: Plugin root: the directory containing forge_cc/, modes/, souls/, bin/.
#: CLAUDE_PLUGIN_ROOT is set by Claude Code inside hook commands; the
#: filesystem walk covers direct CLI use, tests, and pip-installed layouts.
_ENV_ROOT = os.environ.get("CLAUDE_PLUGIN_ROOT")
if _ENV_ROOT and (Path(_ENV_ROOT).expanduser() / "modes").is_dir():
    PLUGIN_ROOT = Path(_ENV_ROOT).expanduser().resolve()
else:
    PLUGIN_ROOT = Path(__file__).resolve().parent.parent


def modes_dir() -> Path:
    override = os.environ.get("FORGE_MODES_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return PLUGIN_ROOT / "modes"


def souls_dir() -> Path:
    return PLUGIN_ROOT / "souls"


def cli_path() -> Path:
    """Absolute path to the `forge` CLI that skills shell out to."""
    return PLUGIN_ROOT / "bin" / "forge"


def ensure_importable() -> None:
    """Put the plugin root on sys.path so `import lib.*` works from anywhere."""
    root = str(PLUGIN_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


# ---------------------------------------------------------------------------
# Current-session pointer
# ---------------------------------------------------------------------------
#
# Hooks receive Claude Code's session_id on stdin, but the `forge` CLI — run
# via the Bash tool from a skill — gets no such thing, and Claude Code exports
# no session-id environment variable. So SessionStart records the mapping and
# the CLI reads it back. Keyed by working directory, so two concurrent Claude
# Code sessions in different projects don't clobber each other.

_POINTER_NAME = "current.json"


def state_dir() -> Path:
    env_dir = os.environ.get("FORGE_STATE_DIR")
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".forge-state"


def _pointer_path() -> Path:
    return state_dir() / _POINTER_NAME


def _load_pointer() -> dict:
    path = _pointer_path()
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def set_current_session(session_id: str, cwd: str | None = None) -> None:
    """Record which Forge session the given working directory is using."""
    data = _load_pointer()
    entry = {"session_id": session_id, "updated_at": time.time()}
    data[str(cwd or os.getcwd())] = entry
    data["_last"] = entry
    path = _pointer_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass  # a missing pointer degrades to "default", it never blocks


def get_current_session(cwd: str | None = None) -> str | None:
    """Resolve the active session id, or None if nothing has been recorded."""
    explicit = os.environ.get("FORGE_SESSION_ID")
    if explicit:
        return explicit

    data = _load_pointer()
    for key in (str(cwd or os.getcwd()), "_last"):
        entry = data.get(key)
        if isinstance(entry, dict) and entry.get("session_id"):
            return str(entry["session_id"])
    return None


# ---------------------------------------------------------------------------
# Mode-change consent
# ---------------------------------------------------------------------------
#
# Relaxing the protocol has to be the user's decision, not the model's. Left
# unguarded, a model that hits the write-lock simply runs the /executor-mode
# skill and writes the file anyway — observed on the first real session test.
# So UserPromptSubmit records when the *user's own prompt* asked for a mode,
# and `forge set-mode` requires that record before it will drop out of a
# thinking mode. Kept in the pointer file rather than the session so that
# `lib/state.py` stays a pure portable core.

def _pointer_key(cwd: str | None) -> str:
    return str(cwd or os.getcwd())


def _update_entry(cwd: str | None, **fields: object) -> None:
    data = _load_pointer()
    key = _pointer_key(cwd)
    entry = data.get(key)
    entry = dict(entry) if isinstance(entry, dict) else {}
    entry.update(fields)
    data[key] = entry
    if isinstance(data.get("_last"), dict):
        last = dict(data["_last"])
        last.update(fields)
        data["_last"] = last
    path = _pointer_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError:
        pass


def set_mode_request(mode: str, cwd: str | None = None) -> None:
    """Record that the user asked for a mode, in their own words."""
    _update_entry(cwd, mode_request=mode, mode_request_at=time.time())


def peek_mode_request(cwd: str | None = None) -> str | None:
    data = _load_pointer()
    for key in (_pointer_key(cwd), "_last"):
        entry = data.get(key)
        if isinstance(entry, dict) and entry.get("mode_request"):
            return str(entry["mode_request"])
    return None


def reset_audit_blocks(cwd: str | None = None) -> None:
    """Start a fresh revision budget. Called when the user takes a turn."""
    _update_entry(cwd, audit_blocks=0)


def bump_audit_blocks(cwd: str | None = None) -> int:
    """Count one audit block against this turn's budget, return the new total."""
    data = _load_pointer()
    entry = data.get(_pointer_key(cwd))
    current = 0
    if isinstance(entry, dict):
        try:
            current = int(entry.get("audit_blocks") or 0)
        except (TypeError, ValueError):
            current = 0
    _update_entry(cwd, audit_blocks=current + 1)
    return current + 1


def audit_blocks(cwd: str | None = None) -> int:
    data = _load_pointer()
    for key in (_pointer_key(cwd), "_last"):
        entry = data.get(key)
        if isinstance(entry, dict) and entry.get("audit_blocks") is not None:
            try:
                return int(entry["audit_blocks"])
            except (TypeError, ValueError):
                return 0
    return 0


def consume_mode_request(cwd: str | None = None) -> str | None:
    """Read and clear the pending user mode request."""
    pending = peek_mode_request(cwd)
    if pending is not None:
        _update_entry(cwd, mode_request=None, mode_request_at=None)
    return pending

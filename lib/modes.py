"""Load and validate mode definitions from YAML files.

YAML is the authored format, but the hook handlers that read these files run
under whatever ``python3`` is on PATH — and a Claude Code plugin cannot
declare pip dependencies, so PyYAML may simply not be importable. Every
``modes/<id>.yaml`` therefore has a committed ``modes/<id>.json`` twin
(regenerate with ``scripts/build_modes_json.py``), and loading falls back to
it when PyYAML is missing. Edit the YAML, never the JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - exercised on hosts without PyYAML
    yaml = None  # type: ignore[assignment]


@dataclass
class Metacognitive:
    checkpoint_interval: int = 0
    prompts: list[str] = field(default_factory=list)
    session_end_prompt: str = ""


@dataclass
class Transitions:
    allowed_from: list[str] = field(default_factory=list)
    allowed_to: list[str] = field(default_factory=list)
    confirm_switch: bool = False


@dataclass
class Behaviors:
    required: list[str] = field(default_factory=list)
    forbidden: list[str] = field(default_factory=list)


@dataclass
class Mode:
    id: str
    name: str
    description: str
    system_prompt_file: str
    behaviors: Behaviors
    input_rules: list[str]
    metacognitive: Metacognitive
    transitions: Transitions = field(default_factory=Transitions)

    def load_system_prompt(self, base_dir: str | Path) -> str:
        """Load the system prompt markdown file relative to base_dir."""
        base = Path(base_dir).resolve()
        path = (base / self.system_prompt_file).resolve()
        try:
            path.relative_to(base)
        except ValueError:
            raise ValueError(f"system_prompt_file escapes base directory: {self.system_prompt_file!r}")
        if not path.exists():
            raise FileNotFoundError(f"System prompt file not found: {path}")
        return path.read_text(encoding="utf-8")


def _read_mapping(path: Path) -> object:
    """Parse a mode file, falling back to a precompiled JSON twin."""
    if path.suffix == ".json":
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    if yaml is not None:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    twin = path.with_suffix(".json")
    if twin.exists():
        with open(twin, encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError(
        f"PyYAML is not installed and no precompiled JSON twin exists for {path}. "
        "Run scripts/build_modes_json.py, or install pyyaml."
    )


def load_mode(path: str | Path) -> Mode:
    """Load a single mode definition from a YAML (or JSON) file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Mode file not found: {path}")

    data = _read_mapping(path)

    if not isinstance(data, dict):
        raise ValueError(f"Invalid mode file (expected mapping): {path}")

    for key in ("id", "name", "description", "system_prompt_file", "behaviors"):
        if key not in data:
            raise ValueError(f"Mode file missing required key '{key}': {path}")

    behaviors_raw = data.get("behaviors", {})
    behaviors = Behaviors(
        required=behaviors_raw.get("required", []),
        forbidden=behaviors_raw.get("forbidden", []),
    )

    input_rules = data.get("input_rules", [])

    meta_raw = data.get("metacognitive", {})
    metacognitive = Metacognitive(
        checkpoint_interval=meta_raw.get("checkpoint_interval", 0),
        prompts=meta_raw.get("prompts", []),
        session_end_prompt=meta_raw.get("session_end_prompt", ""),
    )

    trans_raw = data.get("transitions", {})
    transitions = Transitions(
        allowed_from=trans_raw.get("allowed_from", []),
        allowed_to=trans_raw.get("allowed_to", []),
        confirm_switch=trans_raw.get("confirm_switch", False),
    )

    return Mode(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        system_prompt_file=data["system_prompt_file"],
        behaviors=behaviors,
        input_rules=input_rules,
        metacognitive=metacognitive,
        transitions=transitions,
    )


def load_all_modes(modes_dir: str | Path) -> dict[str, Mode]:
    """Load every mode definition in a directory. Returns dict keyed by mode id.

    Prefers the authored ``*.yaml`` files. On a host without PyYAML, and only
    when no YAML is present to fall back from, the precompiled ``*.json``
    twins are read directly.
    """
    modes_dir = Path(modes_dir)
    if not modes_dir.is_dir():
        raise FileNotFoundError(f"Modes directory not found: {modes_dir}")

    paths = [p for p in sorted(modes_dir.glob("*.yaml")) if p.name != "schema.yaml"]
    if not paths:
        paths = [p for p in sorted(modes_dir.glob("*.json")) if p.name != "schema.json"]

    modes: dict[str, Mode] = {}
    for path in paths:
        mode = load_mode(path)
        if mode.id in modes:
            raise ValueError(f"Duplicate mode id '{mode.id}' in {path}")
        modes[mode.id] = mode

    return modes


VALID_MODE_IDS = {"forge", "anvil", "crucible", "executor"}

#!/usr/bin/env python3
"""Compile modes/*.yaml into committed modes/*.json twins.

The hook handlers run under the system ``python3``, and plugin hooks have no
way to declare pip dependencies — so PyYAML may be missing on a user's
machine. The JSON twins are what ``lib/modes.py`` falls back to.

YAML stays the authored format. Run this after editing any mode file:

    python3 scripts/build_modes_json.py

Requires PyYAML (it is in the ``dev`` extra); ``--check`` verifies the twins
are current without writing, for CI.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MODES_DIR = REPO_ROOT / "modes"


def render(path: Path) -> str:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any twin is missing or stale, without writing",
    )
    args = parser.parse_args()

    sources = [p for p in sorted(MODES_DIR.glob("*.yaml")) if p.name != "schema.yaml"]
    if not sources:
        print(f"no mode files found in {MODES_DIR}", file=sys.stderr)
        return 1

    stale: list[str] = []
    for src in sources:
        target = src.with_suffix(".json")
        rendered = render(src)
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != rendered:
                stale.append(target.name)
            continue
        target.write_text(rendered, encoding="utf-8")
        print(f"wrote {target.relative_to(REPO_ROOT)}")

    if stale:
        print(
            "stale or missing mode JSON twins: " + ", ".join(stale)
            + "\nrun: python3 scripts/build_modes_json.py",
            file=sys.stderr,
        )
        return 1

    if args.check:
        print(f"{len(sources)} mode JSON twins up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

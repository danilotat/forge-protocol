#!/usr/bin/env python3
"""Forge Protocol Stop hook."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from forge_cc import hookio
from forge_cc.handlers import stop

if __name__ == "__main__":
    raise SystemExit(hookio.run(stop))

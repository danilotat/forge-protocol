#!/usr/bin/env python3
"""Forge Protocol SessionEnd hook."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from forge_cc import hookio
from forge_cc.handlers import session_end

if __name__ == "__main__":
    raise SystemExit(hookio.run(session_end))

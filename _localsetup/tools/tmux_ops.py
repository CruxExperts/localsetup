#!/usr/bin/env python3
"""Managed tmux ops workflow: pick/probe/run/status/cancel plus legacy send/wait."""

from __future__ import annotations

from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.core.tmux_ops import main


if __name__ == "__main__":
    sys.exit(main())

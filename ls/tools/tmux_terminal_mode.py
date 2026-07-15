#!/usr/bin/env python3
"""Thin wrapper for tmux terminal mode."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ls.core.tmux_terminal_mode.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())

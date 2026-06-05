#!/usr/bin/env python3
# Purpose: Thin CLI for Agent Q transport client (version, PRD stamp, key doctor stubs).
# Created: 2026-03-09
# Last updated: 2026-03-09

"""Run from repo root: uv run --locked python _localsetup/tools/agentq_transport_client/agentq_cli.py <cmd>"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_ENGINE = _ROOT.parent.parent
sys.path.insert(0, str(_ENGINE))
sys.path.insert(0, str(_ROOT))

from agentq_transport_client.cli_parser import main  # noqa: E402


if __name__ == "__main__":
    sys.exit(main())

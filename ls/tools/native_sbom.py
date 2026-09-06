#!/usr/bin/env python3
"""Emit or verify the external native sandbox SBOM without executing the bundle."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.agent.native_sbom import main

if __name__ == '__main__':
    raise SystemExit(main())

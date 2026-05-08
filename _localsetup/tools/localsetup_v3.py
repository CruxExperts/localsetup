#!/usr/bin/env python3
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.v3.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

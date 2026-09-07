#!/usr/bin/env python3
"""Export or validate the managed SDK external dependency locks."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.sdk_payload.dependencies import main

if __name__ == "__main__":
    raise SystemExit(main())

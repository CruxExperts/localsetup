#!/usr/bin/env python3
"""Provider-free validation of the canonical SDK payload."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.sdk_payload.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Generate or check identical hashed requirements for optional storage skills."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.s3_sdk.exports import main

if __name__ == "__main__":
    raise SystemExit(main())

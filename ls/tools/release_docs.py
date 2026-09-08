#!/usr/bin/env python3
"""Direct release-documentation entrypoint."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.release_docs.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

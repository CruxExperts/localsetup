#!/usr/bin/env python3
"""Generate public doc artifacts from canonical framework sources."""

from __future__ import annotations

from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.core.docs_artifacts.cli import main
from docs_alignment import generate_alignment_artifacts


if __name__ == "__main__":
    raise SystemExit(main(alignment_generator=generate_alignment_artifacts))

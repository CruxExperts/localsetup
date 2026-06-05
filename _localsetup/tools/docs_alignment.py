#!/usr/bin/env python3
"""Inventory, audit, and align repository documentation against source truth."""

from __future__ import annotations

from pathlib import Path
import sys


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.core.docs_alignment import (
    audit,
    build_plan,
    collect_asset_manifest,
    collect_inventory,
    collect_truth_map,
    generate_alignment_artifacts,
    main,
)

__all__ = [
    "audit",
    "build_plan",
    "collect_asset_manifest",
    "collect_inventory",
    "collect_truth_map",
    "generate_alignment_artifacts",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())

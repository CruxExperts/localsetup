#!/usr/bin/env python3
"""Refresh storage SDK response contracts using the explicit s3-sdk group."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.s3_sdk.responses import update


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    update(args.repo_root.resolve(), check=args.check)


if __name__ == "__main__":
    main()

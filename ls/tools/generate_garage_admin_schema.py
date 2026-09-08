#!/usr/bin/env python3
"""Extract reviewed Garage Admin v2 operation schemas for standalone installation."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ls.core.s3_sdk.garage_schema import generate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--source-schema", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    generate(args.repo_root.resolve(), args.source_schema, check=args.check)


if __name__ == "__main__":
    main()

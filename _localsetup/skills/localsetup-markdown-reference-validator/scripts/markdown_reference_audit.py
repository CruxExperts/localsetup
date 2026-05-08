#!/usr/bin/env python3
"""
Run markdown reference audit for myrig using framework skill tooling.

Purpose:
- Provide a repo-level entrypoint that uses the Localsetup markdown-reference-validator skill.
- Keep scheduling commands simple for cron/autostart integrations.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_CONFIG = "_localsetup/skills/localsetup-markdown-reference-validator/markdown_reference_audit.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run markdown reference audit.")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="YAML config path")
    parser.add_argument(
        "--force", action="store_true", help="Run regardless of interval guard"
    )
    parser.add_argument("--reason", default="manual", help="Short run reason label")
    parser.add_argument(
        "--min-interval-seconds",
        type=int,
        default=43_200,
        help="Minimum seconds between non-forced runs (default 12h)",
    )
    parser.add_argument("--jitter-min-seconds", type=int, default=0)
    parser.add_argument("--jitter-max-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    script_dir = Path(__file__).resolve().parent
    validator = script_dir / "markdown_reference_validator.py"

    if not validator.is_file():
        print(f"[ERROR] Validator script not found: {validator}", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[4]

    cmd = [
        sys.executable,
        str(validator),
        "--config",
        str(
            (repo_root / args.config).resolve()
            if not Path(args.config).is_absolute()
            else Path(args.config).resolve()
        ),
        "--reason",
        args.reason,
        "--min-interval-seconds",
        str(args.min_interval_seconds),
        "--jitter-min-seconds",
        str(args.jitter_min_seconds),
        "--jitter-max-seconds",
        str(args.jitter_max_seconds),
    ]

    if args.force:
        cmd.append("--force")

    cp = subprocess.run(cmd, cwd=str(repo_root), check=False)
    return cp.returncode


if __name__ == "__main__":
    raise SystemExit(main())

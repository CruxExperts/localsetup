#!/usr/bin/env python3
"""
Markdown reference validator.

Purpose:
- Parse markdown files from configured targets.
- Validate local file-path references discovered in markdown links and code-span path literals.
- Report missing paths and unresolved local anchors.
- Run safely on schedule (interval guard + optional jitter).

Standards:
- Python-first automation per ls/docs/TOOLING_POLICY.md
- Input hardening per ls/docs/INPUT_HARDENING_STANDARD.md
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime
from pathlib import Path

# Localsetup shared dependency guard (approved pattern)
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # type: ignore  # noqa: E402

require_deps(["yaml"])

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from markdown_reference_config import (  # noqa: E402
    DEFAULT_MIN_INTERVAL_SECONDS,
    Config,
    ValidationError,
    _load_config,
    _normalize_path,
    _read_epoch,
    _sanitize_reason,
)
from markdown_reference_links import _extract_findings, _slugify_heading  # noqa: E402
from markdown_reference_report import _collect_files, _render_report  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate markdown local references from configured targets."
    )
    parser.add_argument("--config", required=True, help="Path to YAML config")
    parser.add_argument(
        "--report-path", default="", help="Optional report output override"
    )
    parser.add_argument(
        "--state-file", default="", help="Optional state-file path override"
    )
    parser.add_argument(
        "--min-interval-seconds", type=int, default=DEFAULT_MIN_INTERVAL_SECONDS
    )
    parser.add_argument(
        "--force", action="store_true", help="Run regardless of interval guard"
    )
    parser.add_argument("--reason", default="manual", help="Short run reason label")
    parser.add_argument("--jitter-min-seconds", type=int, default=0)
    parser.add_argument("--jitter-max-seconds", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.min_interval_seconds < 60:
        print("[ERROR] --min-interval-seconds must be >= 60", file=sys.stderr)
        return 2

    config_path = Path(args.config).expanduser().resolve()
    if not config_path.is_file():
        print(f"[ERROR] Missing config file: {config_path}", file=sys.stderr)
        return 2

    try:
        config = _load_config(config_path)
    except ValidationError as exc:
        print(f"[ERROR] Invalid config: {exc}", file=sys.stderr)
        return 2

    if args.report_path:
        config = Config(
            repo_root=config.repo_root,
            report_path=_normalize_path(
                args.report_path, cwd=config_path.parent, repo_root=config.repo_root
            ),
            state_file=config.state_file,
            max_findings=config.max_findings,
            targets=config.targets,
            kilo_manifests=config.kilo_manifests,
            inline_code_mode=config.inline_code_mode,
            ignore=config.ignore,
        )

    if args.state_file:
        config = Config(
            repo_root=config.repo_root,
            report_path=config.report_path,
            state_file=_normalize_path(
                args.state_file, cwd=config_path.parent, repo_root=config.repo_root
            ),
            max_findings=config.max_findings,
            targets=config.targets,
            kilo_manifests=config.kilo_manifests,
            inline_code_mode=config.inline_code_mode,
            ignore=config.ignore,
        )

    reason = _sanitize_reason(args.reason)

    try:
        config.state_file.parent.mkdir(parents=True, exist_ok=True)
        config.report_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[ERROR] Could not create output directories: {exc}", file=sys.stderr)
        return 2

    now_epoch = int(datetime.now().timestamp())
    if not args.force:
        try:
            last_epoch = _read_epoch(config.state_file)
        except (OSError, ValidationError) as exc:
            print(f"[ERROR] Could not read state file: {exc}", file=sys.stderr)
            return 2
        if (now_epoch - last_epoch) < args.min_interval_seconds:
            return 0

    if args.jitter_max_seconds > 0:
        jitter_min = max(0, args.jitter_min_seconds)
        jitter_max = max(jitter_min, args.jitter_max_seconds)
        time.sleep(random.randint(jitter_min, jitter_max))

    files, manifest_notes = _collect_files(config, config_path)
    findings, checked_refs = _extract_findings(
        files,
        repo_root=config.repo_root,
        inline_code_mode=config.inline_code_mode,
        ignore=config.ignore,
        max_findings=config.max_findings,
    )

    report = _render_report(
        config_path=config_path,
        config=config,
        reason=reason,
        files_scanned=files,
        checked_refs=checked_refs,
        findings=findings,
        manifest_notes=manifest_notes,
    )

    try:
        config.report_path.write_text(report, encoding="utf-8")
        config.state_file.write_text(f"{now_epoch}\n", encoding="utf-8")
    except OSError as exc:
        print(f"[ERROR] Could not write audit outputs: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

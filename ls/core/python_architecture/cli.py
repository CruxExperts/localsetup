from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from .config import BaselineError, load_baseline
from .models import CheckSummary, Finding
from .reporting import render_json, render_markdown
from .rules import evaluate
from .scanner import scan_files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check Localsetup Python architecture constraints.")
    parser.add_argument("--repo-root", required=True, help="Repository root to scan.")
    parser.add_argument("--baseline", required=True, help="Tracked Python architecture baseline JSON path.")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--include-scope", choices=("framework", "skills", "all"), default="framework")
    parser.add_argument("--fail-on", choices=("warnings", "errors"), default="errors")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        repo_root = Path(args.repo_root).expanduser().resolve()
        baseline_path = Path(args.baseline)
        if not baseline_path.is_absolute():
            baseline_path = repo_root / baseline_path
        baseline = load_baseline(baseline_path)
        metrics = scan_files(repo_root, args.include_scope)
        findings = evaluate(repo_root, metrics, baseline, args.include_scope)
        summary = CheckSummary(
            repo_root=str(repo_root),
            include_scope=args.include_scope,
            fail_on=args.fail_on,
            scanned_files=len(metrics),
            findings=tuple(findings),
        )
        output = render_markdown(summary) if args.format == "markdown" else render_json(summary)
        sys.stdout.write(output)
        if args.fail_on == "warnings" and summary.findings:
            return 1
        if summary.errors:
            return 1
        return 0
    except BaselineError as exc:
        repo_root = Path(args.repo_root).expanduser().resolve()
        summary = CheckSummary(
            repo_root=str(repo_root),
            include_scope=args.include_scope,
            fail_on=args.fail_on,
            scanned_files=0,
            findings=(
                Finding(
                    code="PYA004_BASELINE_MALFORMED",
                    severity="error",
                    path=args.baseline,
                    message=str(exc),
                ),
            ),
        )
        output = render_markdown(summary) if args.format == "markdown" else render_json(summary)
        sys.stdout.write(output)
        return 2
    except Exception as exc:
        sys.stderr.write(f"python-architecture-check: {type(exc).__name__}: {exc}\n")
        return 2

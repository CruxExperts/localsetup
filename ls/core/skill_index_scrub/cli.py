from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import yaml

from .audit import audit_skill, is_prunable_dead_url
from .config import index_refresh_status
from .constants import DEFAULT_TIMEOUT, DEFAULT_WORKERS, MIN_DESC_LEN_DEFAULT, TOOL_NAME
from . import diagnostics
from .diagnostics import die, set_debug, warn
from .index_io import apply_fixes
from .reporting import build_report


USAGE = """
Usage:
    python3 skill_index_scrub.py [--fix] [--prune-dead-urls] [--workers N] [--timeout S] [--report FILE]
                                 [--min-desc-len N] [--skip-url-check] [--skip-desc-fetch]

Modes:
    (default)   Dry-run audit: check URLs, detect stubs, report gaps. No writes.
    --fix       Write enriched descriptions back to the index in-place and update 'updated'.
                With --prune-dead-urls, also remove entries whose URLs return 404/410.

Options:
    --workers N         Parallel fetch workers (default: 10).
    --timeout S         HTTP timeout per request in seconds (default: 10).
    --report FILE       Write GFM report to FILE in addition to stdout.
    --prune-dead-urls   With --fix, remove entries whose URLs return 404/410.
    --min-desc-len N    Minimum acceptable description length (default: 20).
    --skip-url-check    Skip HTTP liveness probing (faster, description-only mode).
    --skip-desc-fetch   Skip upstream SKILL.md fetch (URL-check-only mode).
    --name SUBSTR       Only process skills whose name contains SUBSTR (case-insensitive).
    --debug             Verbose debug output to stderr.

Exit codes:
    0  Clean (or fixes applied cleanly)
    1  Issues found (dry-run) or partial failure
    2  Fatal error (bad index path, import failure, etc.)
"""


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--fix", action="store_true", help="Apply fetched descriptions to the index.")
    parser.add_argument(
        "--prune-dead-urls",
        action="store_true",
        help="With --fix and URL checks enabled, remove entries whose URLs return 404/410.",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        metavar="N",
        help=f"Parallel workers (default: {DEFAULT_WORKERS}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        metavar="S",
        help=f"HTTP timeout per request in seconds (default: {DEFAULT_TIMEOUT}).",
    )
    parser.add_argument("--report", type=str, metavar="FILE", help="Write GFM report to FILE in addition to stdout.")
    parser.add_argument(
        "--min-desc-len",
        type=int,
        default=MIN_DESC_LEN_DEFAULT,
        metavar="N",
        help=f"Minimum acceptable description length (default: {MIN_DESC_LEN_DEFAULT}).",
    )
    parser.add_argument("--skip-url-check", action="store_true", help="Skip HTTP liveness probing.")
    parser.add_argument("--skip-desc-fetch", action="store_true", help="Skip upstream SKILL.md fetch.")
    parser.add_argument(
        "--name",
        type=str,
        default="",
        metavar="SUBSTR",
        help="Only audit skills whose name contains SUBSTR (case-insensitive).",
    )
    parser.add_argument("--debug", action="store_true", help="Verbose debug output to stderr.")
    parser.add_argument(
        "--index",
        type=str,
        default="",
        metavar="FILE",
        help="Path to PUBLIC_SKILL_INDEX.yaml (auto-detected if omitted).",
    )
    return parser.parse_args(argv)


def locate_index() -> Path:
    """Find PUBLIC_SKILL_INDEX.yaml relative to the package and repo root."""
    here = Path(__file__).resolve()
    repo_root = here.parents[3]
    candidates = [
        repo_root / "ls" / "docs" / "PUBLIC_SKILL_INDEX.yaml",
        here.parents[2] / "docs" / "PUBLIC_SKILL_INDEX.yaml",
        Path.cwd() / "PUBLIC_SKILL_INDEX.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    die(
        "Cannot locate PUBLIC_SKILL_INDEX.yaml.\n"
        "  Run from the repo root or pass the path directly.\n"
        f"  Searched: {[str(candidate) for candidate in candidates]}"
    )
    raise AssertionError("unreachable")


def validate_args(args: argparse.Namespace) -> None:
    if args.workers < 1 or args.workers > 50:
        die(f"--workers must be between 1 and 50, got {args.workers}")
    if args.timeout < 1 or args.timeout > 120:
        die(f"--timeout must be between 1 and 120, got {args.timeout}")
    if args.min_desc_len < 1:
        die(f"--min-desc-len must be >= 1, got {args.min_desc_len}")
    if args.prune_dead_urls and not args.fix:
        die("--prune-dead-urls requires --fix")
    if args.prune_dead_urls and args.skip_url_check:
        die("--prune-dead-urls requires URL checking; remove --skip-url-check")


def resolve_index_path(args: argparse.Namespace) -> Path:
    if args.index:
        index_path = Path(args.index).expanduser().resolve()
        if not index_path.exists():
            die(f"--index path does not exist: {index_path}")
        return index_path
    return locate_index()


def load_index(index_path: Path) -> dict:
    with open(index_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        die(f"Index is not a valid YAML mapping: {index_path}")
    return data


def audit_skills(skills: list[dict], args: argparse.Namespace) -> list[dict]:
    print(f"[INFO]  Auditing {len(skills)} skills with {args.workers} workers...", file=sys.stderr)
    start = time.monotonic()
    results: list[dict] = []

    def worker(skill: dict) -> dict:
        try:
            return audit_skill(
                skill,
                timeout=args.timeout,
                skip_url_check=args.skip_url_check,
                skip_desc_fetch=args.skip_desc_fetch,
                min_desc_len=args.min_desc_len,
            )
        except Exception as exc:
            if diagnostics.DEBUG:
                traceback.print_exc(file=sys.stderr)
            return {
                "name": skill.get("name", ""),
                "url": skill.get("url", ""),
                "original_desc": "",
                "url_live": None,
                "url_status": None,
                "desc_stub": False,
                "desc_reason": "",
                "fetched_desc": None,
                "fetched_source": None,
                "action": "error",
                "error": str(exc),
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(worker, skill): skill for skill in skills}
        done = 0
        total = len(futures)
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())
            done += 1
            if done % 100 == 0 or done == total:
                elapsed = time.monotonic() - start
                print(f"[INFO]  {done}/{total} done ({elapsed:.1f}s)", file=sys.stderr)

    elapsed = time.monotonic() - start
    print(f"[INFO]  Audit complete in {elapsed:.1f}s", file=sys.stderr)
    return results


def apply_requested_fixes(
    index_path: Path,
    results: list[dict],
    args: argparse.Namespace,
) -> tuple[str | None, bool | None, int]:
    worker_errors = [result for result in results if result["action"] == "error"]
    pruned_dead_urls = 0
    if not args.fix:
        return None, None, pruned_dead_urls

    fixable = [result for result in results if result["action"] == "fixable"]
    dead = [result for result in results if result["url_live"] is False]
    prunable_dead = [result for result in dead if is_prunable_dead_url(result)]
    if worker_errors:
        warn("Skipping --fix because one or more audit workers failed.")
    elif fixable or (args.prune_dead_urls and prunable_dead):
        count, pruned_dead_urls = apply_fixes(index_path, results, prune_dead_urls=args.prune_dead_urls)
        print(f"[INFO]  Applied {count} description fix(es) to {index_path}", file=sys.stderr)
        if args.prune_dead_urls:
            print(f"[INFO]  Pruned {pruned_dead_urls} dead URL entrie(s) from {index_path}", file=sys.stderr)
        index_updated_status, _, index_stale = index_refresh_status(
            datetime.now(timezone.utc),
            datetime.now(timezone.utc),
        )
        return index_updated_status, index_stale, pruned_dead_urls
    else:
        print("[INFO]  No fixable entries found; index unchanged.", file=sys.stderr)
    return None, None, pruned_dead_urls


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    set_debug(args.debug)
    validate_args(args)

    index_path = resolve_index_path(args)
    print(f"[INFO]  Index: {index_path}", file=sys.stderr)

    data = load_index(index_path)
    index_updated_status, _, index_stale = index_refresh_status(data.get("updated"), datetime.now(timezone.utc))
    print(f"[INFO]  Index refresh: {index_updated_status}", file=sys.stderr)
    if index_stale:
        warn(
            "PUBLIC_SKILL_INDEX.yaml is stale or has an invalid updated value; "
            "refresh and scrub before relying on discovery recommendations."
        )

    skills = data.get("skills", [])
    if not isinstance(skills, list):
        die("Index 'skills' field is not a list.")

    if args.name:
        substr = args.name.lower()
        skills = [skill for skill in skills if substr in skill.get("name", "").lower()]
        print(f"[INFO]  Filtered to {len(skills)} skills matching --name {args.name!r}", file=sys.stderr)

    if not skills:
        print("[INFO]  No skills to audit.", file=sys.stderr)
        return 0

    results = audit_skills(skills, args)
    fix_status, fix_stale, pruned_dead_urls = apply_requested_fixes(index_path, results, args)
    if fix_status is not None:
        index_updated_status = fix_status
    if fix_stale is not None:
        index_stale = fix_stale

    report = build_report(results, args, index_updated_status, index_stale, pruned_dead_urls=pruned_dead_urls)
    print(report)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"[INFO]  Report written to {args.report}", file=sys.stderr)

    worker_errors = [result for result in results if result["action"] == "error"]
    dead = [result for result in results if result["url_live"] is False]
    stubs = [result for result in results if result["desc_stub"] and result["action"] != "fixable"]
    unfixed_stubs = [result for result in stubs if not args.fix]

    if worker_errors:
        return 1
    if (dead or unfixed_stubs) and not args.fix:
        return 1
    return 0

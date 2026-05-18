#!/usr/bin/env python3
# Purpose: Audit PUBLIC_SKILL_INDEX.yaml for dead URLs, stub descriptions, and schema gaps.
#          Optionally fetch real descriptions from upstream SKILL.md/README.md and write fixes.
# Created: 2026-02-27
# Last Updated: 2026-02-27
# Requires: PyYAML, requests, python-frontmatter (see _localsetup/requirements.txt)

"""
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

import argparse
import concurrent.futures
import os
import re
import sys
import time
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

# Resolve lib/ relative to this tool (tools/ -> lib/)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["yaml", "requests", "frontmatter"])

import frontmatter  # noqa: E402
import requests  # noqa: E402
import yaml  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_VERSION = "1.0.0"
TOOL_NAME = "skill_index_scrub"

MAX_DESC_LEN = 300
MIN_DESC_LEN_DEFAULT = 20
DEFAULT_WORKERS = 10
DEFAULT_TIMEOUT = 10
MAX_FIELD_LEN = 4096
HARD_DEAD_URL_STATUSES = {404, 410}

# Placeholder patterns that indicate the description was auto-generated, not fetched
STUB_PATTERNS = [
    re.compile(r"^anthropic skill:", re.IGNORECASE),
    re.compile(r"^openclaw skill:", re.IGNORECASE),
    re.compile(r"^clawdhub skill:", re.IGNORECASE),
]

# Upstream file candidates to fetch for description enrichment (in priority order)
UPSTREAM_FILENAMES = ["SKILL.md", "README.md", "readme.md", "skill.md"]

# Control characters to strip (but preserve \t, \n for paragraph extraction)
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEBUG = False


def _debug(msg: str) -> None:
    if _DEBUG:
        print(f"[DEBUG] {msg}", file=sys.stderr)


def _warn(msg: str) -> None:
    print(f"[WARN]  {msg}", file=sys.stderr)


def _die(msg: str, code: int = 2) -> None:
    print(f"[FATAL] {msg}", file=sys.stderr)
    sys.exit(code)


def _sanitize(value: str, max_len: int = MAX_FIELD_LEN) -> str:
    """Strip control chars, collapse whitespace, truncate."""
    if not value:
        return ""
    cleaned = _CTRL_RE.sub("", value)
    cleaned = " ".join(cleaned.split()).strip()
    return cleaned[:max_len] if max_len else cleaned


def _parse_index_updated(value: object) -> Optional[datetime]:
    """Parse PUBLIC_SKILL_INDEX.yaml updated values into UTC datetimes."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = f"{raw[:-1]}+00:00"
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_age(days: int) -> str:
    if days < 14:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit}"
    if days < 365:
        weeks = days // 7
        unit = "week" if weeks == 1 else "weeks"
        return f"{weeks} {unit}"
    years = days // 365
    unit = "year" if years == 1 else "years"
    return f"{years} {unit}"


def index_refresh_status(updated: object, now: datetime) -> tuple[str, Optional[int], bool]:
    """Return display text, age in days, and whether the index is stale."""
    parsed = _parse_index_updated(updated)
    if parsed is None:
        if updated:
            raw = _sanitize(str(updated), max_len=120)
            return f"unparseable ({raw})", None, True
        return "missing / never refreshed", None, True

    age_days = (now.date() - parsed.date()).days
    if age_days < 0:
        future_days = abs(age_days)
        unit = "day" if future_days == 1 else "days"
        return f"{parsed.strftime('%Y-%m-%d')} ({future_days} {unit} in the future)", age_days, True
    return f"{parsed.strftime('%Y-%m-%d')} ({_format_age(age_days)} ago)", age_days, age_days >= 7


# ---------------------------------------------------------------------------
# URL utilities
# ---------------------------------------------------------------------------

def _tree_to_raw(url: str) -> str:
    """Convert a github.com tree URL to raw.githubusercontent.com."""
    raw = url.replace("https://github.com/", "https://raw.githubusercontent.com/")
    raw = re.sub(r"/tree/(main|master)/", r"/\1/", raw)
    return raw


def _raw_skill_candidates(tree_url: str) -> list[str]:
    """
    Build a list of raw URLs to try for description fetching.
    If the tree_url already ends in .md, use it directly then strip to directory.
    Otherwise treat as directory and try each UPSTREAM_FILENAMES candidate.
    """
    raw_base = _tree_to_raw(tree_url)
    candidates = []

    if raw_base.endswith(".md"):
        candidates.append(raw_base)
        # Also try the directory (strip filename) for alternate filenames
        base_dir = raw_base.rsplit("/", 1)[0]
        for fn in UPSTREAM_FILENAMES:
            alt = f"{base_dir}/{fn}"
            if alt not in candidates:
                candidates.append(alt)
    else:
        base_dir = raw_base.rstrip("/")
        for fn in UPSTREAM_FILENAMES:
            candidates.append(f"{base_dir}/{fn}")

    return candidates


# ---------------------------------------------------------------------------
# HTTP session
# ---------------------------------------------------------------------------

def _make_session() -> requests.Session:
    sess = requests.Session()
    sess.headers["User-Agent"] = f"localsetup-{TOOL_NAME}/{TOOL_VERSION}"
    return sess


_SESSION: Optional[requests.Session] = None


def _session() -> requests.Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = _make_session()
    return _SESSION


# ---------------------------------------------------------------------------
# HTTP fetch
# ---------------------------------------------------------------------------

def check_url_liveness(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[bool, int]:
    """
    Returns (is_live, status_code).
    Tries HEAD first; falls back to GET if HEAD returns 405.
    """
    sess = _session()
    try:
        resp = sess.head(url, timeout=timeout, allow_redirects=True)
        status = resp.status_code
        if status == 405:
            resp = sess.get(url, timeout=timeout, allow_redirects=True)
            status = resp.status_code
    except requests.RequestException as exc:
        _debug(f"HEAD {url} => network error: {exc}")
        return False, 0
    live = 200 <= status < 400
    return live, status


def is_prunable_dead_url(result: dict) -> bool:
    """Return True only for hard-dead URLs that are safe to prune automatically."""
    return result.get("url_live") is False and result.get("url_status") in HARD_DEAD_URL_STATUSES


def _fetch_text(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[int, str]:
    """GET url; returns (status_code, body). On network error returns (0, '')."""
    sess = _session()
    try:
        resp = sess.get(url, timeout=timeout, allow_redirects=True)
        return resp.status_code, resp.text
    except requests.RequestException as exc:
        _debug(f"GET {url} => network error: {exc}")
        return 0, ""


# ---------------------------------------------------------------------------
# Description extraction from upstream content
# ---------------------------------------------------------------------------

def extract_description_from_content(text: str) -> Optional[str]:
    """
    Parse frontmatter with python-frontmatter; use description field if present
    and long enough, otherwise fall back to the first substantive paragraph of
    the body content.
    """
    try:
        post = frontmatter.loads(text)
        desc = (post.metadata.get("description") or "").strip()
        if len(desc) > 15:
            return desc[:MAX_DESC_LEN]
        for para in re.split(r"\n\s*\n", post.content):
            clean = re.sub(r"[#*`>\[\]|]", "", para).strip()
            clean = _sanitize(clean)
            if len(clean) > 25:
                return clean[:MAX_DESC_LEN]
    except Exception:
        pass
    return None


def fetch_upstream_description(skill_url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[Optional[str], Optional[str]]:
    """
    Try to fetch a description from the skill's upstream repo.
    Returns (description, source_url_used) or (None, None).
    """
    candidates = _raw_skill_candidates(skill_url)
    for raw_url in candidates:
        _debug(f"Trying upstream: {raw_url}")
        status, body = _fetch_text(raw_url, timeout=timeout)
        if status == 200 and len(body) > 50:
            desc = extract_description_from_content(body)
            if desc:
                return desc, raw_url
    return None, None


# ---------------------------------------------------------------------------
# Stub / quality detection
# ---------------------------------------------------------------------------

def is_stub_description(desc: str, min_len: int = MIN_DESC_LEN_DEFAULT) -> tuple[bool, str]:
    """
    Returns (is_stub, reason).
    A stub is: empty, too short, matches a known placeholder pattern, or is just the skill name repeated.
    """
    if not desc or not desc.strip():
        return True, "empty"
    desc = desc.strip()
    if len(desc) < min_len:
        return True, f"too_short ({len(desc)} chars)"
    for pat in STUB_PATTERNS:
        if pat.search(desc):
            return True, f"placeholder_pattern ({pat.pattern!r})"
    # Looks like raw markdown artifact
    if desc.startswith("```") or desc.startswith("|.") or desc.startswith(">-"):
        return True, "markdown_artifact"
    return False, ""


# ---------------------------------------------------------------------------
# Per-skill audit worker
# ---------------------------------------------------------------------------

def audit_skill(
    skill: dict,
    timeout: int,
    skip_url_check: bool,
    skip_desc_fetch: bool,
    min_desc_len: int,
) -> dict:
    """
    Audit a single skill entry. Returns a result dict with:
        name, url, url_live, url_status, desc_stub, desc_reason,
        fetched_desc, fetched_source, action
    """
    name = skill.get("name", "")
    url = skill.get("url", "")
    desc = (skill.get("description") or "").strip()

    result = {
        "name": name,
        "url": url,
        "original_desc": desc,
        "url_live": None,
        "url_status": None,
        "desc_stub": False,
        "desc_reason": "",
        "fetched_desc": None,
        "fetched_source": None,
        "action": "ok",
    }

    # URL liveness
    if not skip_url_check and url:
        live, status = check_url_liveness(url, timeout=timeout)
        result["url_live"] = live
        result["url_status"] = status
        if not live:
            result["action"] = "dead_url"
            _debug(f"{name}: dead URL ({status})")

    # Description quality
    stub, reason = is_stub_description(desc, min_len=min_desc_len)
    result["desc_stub"] = stub
    result["desc_reason"] = reason

    if stub and result["action"] == "ok":
        result["action"] = "stub_desc"

    # Fetch upstream description if stub or short
    if stub and not skip_desc_fetch and url:
        fetched, source = fetch_upstream_description(url, timeout=timeout)
        if fetched:
            result["fetched_desc"] = fetched
            result["fetched_source"] = source
            result["action"] = "fixable" if result["action"] in ("stub_desc", "ok") else result["action"]
            _debug(f"{name}: fetched description from {source}")
        else:
            _debug(f"{name}: could not fetch upstream description")

    return result


# ---------------------------------------------------------------------------
# Report generation (GFM)
# ---------------------------------------------------------------------------

def build_report(
    results: list[dict],
    args: argparse.Namespace,
    index_updated_status: str,
    index_stale: bool,
    pruned_dead_urls: int = 0,
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    dead = [r for r in results if r["url_live"] is False]
    stubs = [r for r in results if r["desc_stub"]]
    fixable = [r for r in results if r["action"] == "fixable"]
    worker_errors = [r for r in results if r["action"] == "error"]
    ok = [r for r in results if r["action"] == "ok"]

    lines = [
        f"# Public skill index scrub report",
        f"",
        f"Generated: {now}  ",
        f"Index refresh: {index_updated_status}  ",
        f"Refresh threshold: 7 days  ",
        f"Total skills audited: {len(results)}  ",
        f"URL check: {'skipped' if args.skip_url_check else 'enabled'}  ",
        f"Description fetch: {'skipped' if args.skip_desc_fetch else 'enabled'}  ",
        f"Mode: {'--fix (applied)' if args.fix else 'dry-run'}  ",
        f"",
        f"## Summary",
        f"",
        f"| Category | Count |",
        f"|---|---|",
        f"| Dead / unreachable URLs | {len(dead)} |",
        f"| Stub or too-short descriptions | {len(stubs)} |",
        f"| Fixable (upstream desc found) | {len(fixable)} |",
        f"| Pruned dead URLs | {pruned_dead_urls} |",
        f"| Worker errors | {len(worker_errors)} |",
        f"| Clean | {len(ok)} |",
        f"",
    ]

    if index_stale:
        lines += [
            f"## Index Refresh Warning",
            f"",
            f"The public skill index is stale or has an invalid `updated` value: {index_updated_status}. Refresh and scrub it before relying on discovery recommendations.",
            f"",
        ]

    if worker_errors:
        lines += [
            f"## Worker Errors ({len(worker_errors)})",
            f"",
            f"| Name | URL | Error |",
            f"|---|---|---|",
        ]
        for r in worker_errors:
            name = _sanitize(r["name"])[:60]
            url = _sanitize(r["url"], max_len=100)
            error = _sanitize(r.get("error", ""), max_len=160).replace("|", "/")
            lines.append(f"| `{name}` | {url} | {error} |")
        lines.append("")

    if dead and not args.skip_url_check:
        lines += [
            f"## Dead URLs ({len(dead)})",
            f"",
            f"| Name | URL | HTTP Status |",
            f"|---|---|---|",
        ]
        for r in dead:
            name = _sanitize(r["name"])[:60]
            url = r["url"][:100]
            status = r["url_status"]
            lines.append(f"| `{name}` | {url} | {status} |")
        lines.append("")

    if stubs:
        lines += [
            f"## Stub descriptions ({len(stubs)})",
            f"",
            f"| Name | Reason | Upstream found? |",
            f"|---|---|---|",
        ]
        for r in stubs:
            name = _sanitize(r["name"])[:60]
            reason = r["desc_reason"]
            found = "yes" if r["fetched_desc"] else ("skipped" if args.skip_desc_fetch else "no")
            lines.append(f"| `{name}` | {reason} | {found} |")
        lines.append("")

    if fixable and not args.fix:
        lines += [
            f"## Fixable entries (re-run with --fix to apply, {len(fixable)} total)",
            f"",
            f"| Name | New description (truncated) | Source |",
            f"|---|---|---|",
        ]
        for r in fixable:
            name = _sanitize(r["name"])[:60]
            desc_preview = (r["fetched_desc"] or "")[:80].replace("|", "/")
            source = (r["fetched_source"] or "")[-80:]
            lines.append(f"| `{name}` | {desc_preview} | `{source}` |")
        lines.append("")

    if args.fix and fixable:
        lines += [
            f"## Applied fixes ({len(fixable)} entries updated)",
            f"",
            f"| Name | Source |",
            f"|---|---|",
        ]
        for r in fixable:
            name = _sanitize(r["name"])[:60]
            source = (r["fetched_source"] or "")[-80:]
            lines.append(f"| `{name}` | `{source}` |")
        lines.append("")

    if not dead and not stubs:
        lines += ["## Result", "", "All audited entries passed. Index looks clean.", ""]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Apply fixes to index
# ---------------------------------------------------------------------------

def apply_fixes(index_path: Path, results: list[dict], *, prune_dead_urls: bool = False) -> tuple[int, int]:
    """Write fetched descriptions and optional dead URL pruning back to the index."""
    with open(index_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    skills = data.get("skills", [])
    # Build lookup by stable entry identity; names can repeat across registries.
    fix_map: dict[tuple[str, str], str] = {}
    dead_keys: set[tuple[str, str]] = set()
    for r in results:
        if r["action"] == "fixable" and r["fetched_desc"]:
            fix_map[(r["name"], r["url"])] = r["fetched_desc"]
        if prune_dead_urls and is_prunable_dead_url(r):
            dead_keys.add((r["name"], r["url"]))

    updated_count = 0
    pruned_count = 0
    kept_skills = []
    for s in skills:
        name = s.get("name", "")
        url = s.get("url", "")
        key = (name, url)
        if key in dead_keys:
            pruned_count += 1
            continue
        if key in fix_map:
            new_desc = fix_map[key]
            s["description"] = new_desc
            s["summary_short"] = new_desc[:120]
            s["summary_long"] = new_desc
            # Refresh quality_signals
            qs = s.get("quality_signals", {})
            qs["has_description"] = True
            qs["description_length"] = len(new_desc)
            s["quality_signals"] = qs
            updated_count += 1
        kept_skills.append(s)

    if prune_dead_urls:
        data["skills"] = kept_skills
    data["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    with open(index_path, "w", encoding="utf-8") as f:
        f.write("# Public skill index - refresh periodically from PUBLIC_SKILL_REGISTRY.urls.\n")
        f.write("# Used by ls-skill-discovery to recommend similar public skills when\n")
        f.write("# the user is creating or importing a skill. Schema: sources, updated (ISO8601), skills.\n")
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False, width=1000)

    return updated_count, pruned_count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--fix", action="store_true", help="Apply fetched descriptions to the index.")
    p.add_argument("--prune-dead-urls", action="store_true",
                   help="With --fix and URL checks enabled, remove entries whose URLs return 404/410.")
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS, metavar="N",
                   help=f"Parallel workers (default: {DEFAULT_WORKERS}).")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, metavar="S",
                   help=f"HTTP timeout per request in seconds (default: {DEFAULT_TIMEOUT}).")
    p.add_argument("--report", type=str, metavar="FILE",
                   help="Write GFM report to FILE in addition to stdout.")
    p.add_argument("--min-desc-len", type=int, default=MIN_DESC_LEN_DEFAULT, metavar="N",
                   help=f"Minimum acceptable description length (default: {MIN_DESC_LEN_DEFAULT}).")
    p.add_argument("--skip-url-check", action="store_true",
                   help="Skip HTTP liveness probing.")
    p.add_argument("--skip-desc-fetch", action="store_true",
                   help="Skip upstream SKILL.md fetch.")
    p.add_argument("--name", type=str, default="", metavar="SUBSTR",
                   help="Only audit skills whose name contains SUBSTR (case-insensitive).")
    p.add_argument("--debug", action="store_true", help="Verbose debug output to stderr.")
    p.add_argument("--index", type=str, default="", metavar="FILE",
                   help="Path to PUBLIC_SKILL_INDEX.yaml (auto-detected if omitted).")
    return p.parse_args()


def locate_index() -> Path:
    """Find PUBLIC_SKILL_INDEX.yaml relative to this script."""
    here = Path(__file__).resolve()
    # Expected: _localsetup/tools/skill_index_scrub.py -> _localsetup/docs/
    candidates = [
        here.parents[1] / "docs" / "PUBLIC_SKILL_INDEX.yaml",
        here.parents[2] / "_localsetup" / "docs" / "PUBLIC_SKILL_INDEX.yaml",
        here.parent / "PUBLIC_SKILL_INDEX.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c
    _die(
        "Cannot locate PUBLIC_SKILL_INDEX.yaml.\n"
        "  Run from the repo root or pass the path directly.\n"
        f"  Searched: {[str(c) for c in candidates]}"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    global _DEBUG
    _DEBUG = args.debug

    # Validate args
    if args.workers < 1 or args.workers > 50:
        _die(f"--workers must be between 1 and 50, got {args.workers}")
    if args.timeout < 1 or args.timeout > 120:
        _die(f"--timeout must be between 1 and 120, got {args.timeout}")
    if args.min_desc_len < 1:
        _die(f"--min-desc-len must be >= 1, got {args.min_desc_len}")
    if args.prune_dead_urls and not args.fix:
        _die("--prune-dead-urls requires --fix")
    if args.prune_dead_urls and args.skip_url_check:
        _die("--prune-dead-urls requires URL checking; remove --skip-url-check")

    if args.index:
        index_path = Path(args.index).expanduser().resolve()
        if not index_path.exists():
            _die(f"--index path does not exist: {index_path}")
    else:
        index_path = locate_index()
    print(f"[INFO]  Index: {index_path}", file=sys.stderr)

    with open(index_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        _die(f"Index is not a valid YAML mapping: {index_path}")

    index_updated_status, _, index_stale = index_refresh_status(
        data.get("updated"),
        datetime.now(timezone.utc),
    )
    print(f"[INFO]  Index refresh: {index_updated_status}", file=sys.stderr)
    if index_stale:
        _warn(
            "PUBLIC_SKILL_INDEX.yaml is stale or has an invalid updated value; "
            "refresh and scrub before relying on discovery recommendations."
        )

    skills = data.get("skills", [])
    if not isinstance(skills, list):
        _die("Index 'skills' field is not a list.")

    # Filter by name if requested
    if args.name:
        substr = args.name.lower()
        skills = [s for s in skills if substr in s.get("name", "").lower()]
        print(f"[INFO]  Filtered to {len(skills)} skills matching --name {args.name!r}", file=sys.stderr)

    if not skills:
        print("[INFO]  No skills to audit.", file=sys.stderr)
        return 0

    print(f"[INFO]  Auditing {len(skills)} skills with {args.workers} workers...", file=sys.stderr)
    t0 = time.monotonic()

    results: list[dict] = []

    def _worker(skill: dict) -> dict:
        try:
            return audit_skill(
                skill,
                timeout=args.timeout,
                skip_url_check=args.skip_url_check,
                skip_desc_fetch=args.skip_desc_fetch,
                min_desc_len=args.min_desc_len,
            )
        except Exception as exc:
            if _DEBUG:
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
        futures = {pool.submit(_worker, s): s for s in skills}
        done = 0
        total = len(futures)
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())
            done += 1
            if done % 100 == 0 or done == total:
                elapsed = time.monotonic() - t0
                print(f"[INFO]  {done}/{total} done ({elapsed:.1f}s)", file=sys.stderr)

    elapsed = time.monotonic() - t0
    print(f"[INFO]  Audit complete in {elapsed:.1f}s", file=sys.stderr)

    # Apply fixes if requested
    worker_errors = [r for r in results if r["action"] == "error"]

    pruned_dead_urls = 0
    if args.fix:
        fixable = [r for r in results if r["action"] == "fixable"]
        dead = [r for r in results if r["url_live"] is False]
        prunable_dead = [r for r in dead if is_prunable_dead_url(r)]
        if worker_errors:
            _warn("Skipping --fix because one or more audit workers failed.")
        elif fixable or (args.prune_dead_urls and prunable_dead):
            count, pruned_dead_urls = apply_fixes(index_path, results, prune_dead_urls=args.prune_dead_urls)
            print(f"[INFO]  Applied {count} description fix(es) to {index_path}", file=sys.stderr)
            if args.prune_dead_urls:
                print(f"[INFO]  Pruned {pruned_dead_urls} dead URL entrie(s) from {index_path}", file=sys.stderr)
            index_updated_status, _, index_stale = index_refresh_status(
                datetime.now(timezone.utc),
                datetime.now(timezone.utc),
            )
        else:
            print("[INFO]  No fixable entries found; index unchanged.", file=sys.stderr)

    # Build and emit report
    report = build_report(results, args, index_updated_status, index_stale, pruned_dead_urls=pruned_dead_urls)
    print(report)

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")
        print(f"[INFO]  Report written to {args.report}", file=sys.stderr)

    # Exit code: 1 if issues found (in dry-run), 0 if clean or fixed
    dead = [r for r in results if r["url_live"] is False]
    stubs = [r for r in results if r["desc_stub"] and r["action"] != "fixable"]
    unfixed_stubs = [r for r in stubs if not args.fix]

    if worker_errors:
        return 1
    if (dead or unfixed_stubs) and not args.fix:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

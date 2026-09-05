from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .config import sanitize


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
    dead_summary = "not checked" if args.skip_url_check else str(len(dead))
    liveness_complete = args.skip_url_check or all(
        not r.get("url") or r.get("url_live") is not None for r in results
    )

    lines = [
        "# Public skill index scrub report",
        "",
        f"Generated: {now}  ",
        f"Index refresh: {index_updated_status}  ",
        "Refresh threshold: 7 days  ",
        f"Total skills audited: {len(results)}  ",
        f"URL check: {'skipped' if args.skip_url_check else 'enabled'}  ",
        f"Description fetch: {'skipped' if args.skip_desc_fetch else 'enabled'}  ",
        f"Mode: {'--fix (applied)' if args.fix else 'dry-run'}  ",
        "",
        "## Summary",
        "",
        "| Category | Count |",
        "|---|---|",
        f"| Dead / unreachable URLs | {dead_summary} |",
        f"| Stub or too-short descriptions | {len(stubs)} |",
        f"| Fixable (upstream desc found) | {len(fixable)} |",
        f"| Pruned dead URLs | {pruned_dead_urls} |",
        f"| Worker errors | {len(worker_errors)} |",
        f"| Clean | {len(ok)} |",
        "",
    ]

    if index_stale:
        lines += [
            "## Index Refresh Warning",
            "",
            "The public skill index is stale or has an invalid `updated` value: "
            f"{index_updated_status}. Refresh and scrub it before relying on discovery recommendations.",
            "",
        ]

    if worker_errors:
        lines += [f"## Worker Errors ({len(worker_errors)})", "", "| Name | URL | Error |", "|---|---|---|"]
        for result in worker_errors:
            name = sanitize(result["name"])[:60]
            url = sanitize(result["url"], max_len=100)
            error = sanitize(result.get("error", ""), max_len=160).replace("|", "/")
            lines.append(f"| `{name}` | {url} | {error} |")
        lines.append("")

    if dead and not args.skip_url_check:
        lines += [f"## Dead URLs ({len(dead)})", "", "| Name | URL | HTTP Status |", "|---|---|---|"]
        for result in dead:
            name = sanitize(result["name"])[:60]
            url = result["url"][:100]
            status = result["url_status"]
            lines.append(f"| `{name}` | {url} | {status} |")
        lines.append("")

    if stubs:
        lines += [f"## Stub descriptions ({len(stubs)})", "", "| Name | Reason | Upstream found? |", "|---|---|---|"]
        for result in stubs:
            name = sanitize(result["name"])[:60]
            reason = result["desc_reason"]
            found = "yes" if result["fetched_desc"] else ("skipped" if args.skip_desc_fetch else "no")
            lines.append(f"| `{name}` | {reason} | {found} |")
        lines.append("")

    if fixable and not args.fix:
        lines += [
            f"## Fixable entries (re-run with --fix to apply, {len(fixable)} total)",
            "",
            "| Name | New description (truncated) | Source |",
            "|---|---|---|",
        ]
        for result in fixable:
            name = sanitize(result["name"])[:60]
            desc_preview = (result["fetched_desc"] or "")[:80].replace("|", "/")
            source = (result["fetched_source"] or "")[-80:]
            lines.append(f"| `{name}` | {desc_preview} | `{source}` |")
        lines.append("")

    if args.fix and fixable:
        lines += [f"## Applied fixes ({len(fixable)} entries updated)", "", "| Name | Source |", "|---|---|"]
        for result in fixable:
            name = sanitize(result["name"])[:60]
            source = (result["fetched_source"] or "")[-80:]
            lines.append(f"| `{name}` | `{source}` |")
        lines.append("")

    if not dead and not stubs and not worker_errors and liveness_complete:
        if args.skip_url_check:
            result = "All audited description checks passed. URL liveness was not checked."
        else:
            result = "All audited description and URL-liveness checks passed."
        lines += ["## Result", "", result, ""]

    return "\n".join(lines)

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .assets import collect_asset_manifest, write_assets_readme
from .audit import audit, build_plan
from .constants import ASSET_MANIFEST_PATH, ASSETS_README, AUDIT_PATH, INVENTORY_PATH, SCHEMA_VERSION, SUMMARY_PATH, TRUTH_MAP_PATH
from .inventory import collect_inventory, collect_truth_map
from .io import _write_json
from .writers import _replace_managed_public_counts, generate_alignment_artifacts


def _repo_root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else Path(__file__).resolve().parents[3]

def _print_or_write(payload: dict[str, Any], output: str | None) -> None:
    if output:
        _write_json(Path(output).expanduser().resolve(), payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _explain(repo_root: Path, claim_id: str | None, path_value: str | None) -> dict[str, Any]:
    truth = collect_truth_map(repo_root)
    if claim_id:
        return {
            "schema_version": SCHEMA_VERSION,
            "claim_id": claim_id,
            "claim": truth["truths"].get(claim_id),
        }
    inventory = collect_inventory(repo_root)
    matches = [row for row in inventory["docs"] if row["path"] == path_value]
    return {"schema_version": SCHEMA_VERSION, "path": path_value, "matches": matches}


def _github_summary(audit_result: dict[str, Any]) -> str:
    lines = [
        "## Documentation Alignment",
        "",
        f"- Status: {'pass' if audit_result['ok'] else 'fail'}",
        f"- Findings: {audit_result['finding_count']}",
        f"- Critical: {audit_result['critical_count']}",
        f"- Major: {audit_result['major_count']}",
        "",
        "Reproduce locally:",
        "",
        "```bash",
        "uv run --locked python _localsetup/tools/docs_alignment.py --repo-root . check --ci",
        "```",
    ]
    for finding in audit_result["findings"][:10]:
        location = finding["path"] if finding["line"] is None else f"{finding['path']}:{finding['line']}"
        lines.append(f"- `{finding['severity']}` {location}: {finding['message']}")
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit and align repository documentation.")
    parser.add_argument("--repo-root", default=None)
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name in ("inventory", "audit", "plan", "assets"):
        child = sub.add_parser(name)
        child.add_argument("--output")
    apply_p = sub.add_parser("apply")
    apply_p.add_argument("--scope", choices=["generated", "public", "assets", "all"], default="generated")
    apply_p.add_argument("--dry-run", action="store_true")
    check_p = sub.add_parser("check")
    check_p.add_argument("--ci", action="store_true")
    check_p.add_argument("--summary-output")
    explain_p = sub.add_parser("explain")
    group = explain_p.add_mutually_exclusive_group(required=True)
    group.add_argument("--claim-id")
    group.add_argument("--path")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = _repo_root(args.repo_root)
    if args.cmd == "inventory":
        _print_or_write(collect_inventory(repo_root), args.output)
        return 0
    if args.cmd == "audit":
        _print_or_write(audit(repo_root), args.output)
        return 0
    if args.cmd == "plan":
        _print_or_write(build_plan(audit(repo_root)), args.output)
        return 0
    if args.cmd == "assets":
        manifest = collect_asset_manifest(repo_root)
        _print_or_write(manifest, args.output)
        return 0
    if args.cmd == "apply":
        changed: dict[str, Any] = {"schema_version": SCHEMA_VERSION, "dry_run": args.dry_run, "changed": []}
        if args.scope in {"generated", "all"}:
            if args.dry_run:
                changed["changed"].extend([str(INVENTORY_PATH), str(TRUTH_MAP_PATH), str(ASSET_MANIFEST_PATH), str(AUDIT_PATH), str(SUMMARY_PATH)])
            else:
                changed["generated"] = generate_alignment_artifacts(repo_root)
                changed["changed"].extend(changed["generated"].values())
        if args.scope in {"public", "all"}:
            changed["changed"].extend(_replace_managed_public_counts(repo_root, args.dry_run))
        if args.scope in {"assets", "all"}:
            manifest = collect_asset_manifest(repo_root)
            if write_assets_readme(repo_root, manifest, dry_run=args.dry_run):
                changed["changed"].append(str(ASSETS_README))
            if not args.dry_run:
                _write_json(repo_root / ASSET_MANIFEST_PATH, manifest, repo_root=repo_root)
        print(json.dumps(changed, indent=2, sort_keys=True))
        return 0
    if args.cmd == "check":
        result = audit(repo_root)
        if args.summary_output:
            Path(args.summary_output).expanduser().resolve().write_text(_github_summary(result), encoding="utf-8")
        elif args.ci and sys.stdout.isatty():
            print(_github_summary(result), end="")
        else:
            print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["ok"] else 1
    if args.cmd == "explain":
        print(json.dumps(_explain(repo_root, args.claim_id, args.path), indent=2, sort_keys=True))
        return 0
    return 2

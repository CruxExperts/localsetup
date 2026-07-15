from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ls.core.provenance import base_provenance, markdown_with_provenance

from .assets import collect_asset_manifest, write_assets_readme
from .audit import audit
from .constants import ASSET_MANIFEST_PATH, ASSETS_README, AUDIT_PATH, INVENTORY_PATH, SUMMARY_PATH, TRUTH_MAP_PATH
from .inventory import collect_inventory, collect_truth_map
from .io import _artifact_id, _read_text, _write_json

def _replace_managed_public_counts(repo_root: Path, dry_run: bool) -> list[str]:
    truth = collect_truth_map(repo_root)["truths"]
    skill_count = truth["skill_count"]["value"]
    workflow_count = truth["workflow_count"]["value"]
    replacements = {
        "README.md": (
            re.compile(r"\b\d+\s+shipped capability skills plus \d+\s+first-class workflow packages\b"),
            f"{skill_count} shipped capability skills plus {workflow_count} first-class workflow packages",
        ),
        "ls/docs/FEATURES.md": (
            re.compile(r"\|\s*\d+\s+shipped skills plus \d+\s+workflow packages\s*\|"),
            f"| {skill_count} shipped skills plus {workflow_count} workflow packages |",
        ),
        "ls/docs/PLATFORM_REGISTRY.md": (
            re.compile(r"\*\*Purpose:\*\* Single source of truth for which AI agent platforms the framework supports\."),
            "**Purpose:** Canonical human-readable registry for which AI agent platforms the framework supports.",
        ),
    }
    changed: list[str] = []
    for rel, (pattern, replacement) in replacements.items():
        path = repo_root / rel
        if not path.exists():
            continue
        text = _read_text(path)
        new_text = pattern.sub(replacement, text)
        if new_text != text:
            changed.append(rel)
            if not dry_run:
                path.write_text(new_text, encoding="utf-8")
    return changed


def write_summary(repo_root: Path, inventory: dict[str, Any], audit_result: dict[str, Any]) -> None:
    truth = collect_truth_map(repo_root)["truths"]
    lines = [
        "---",
        "status: ACTIVE",
        f"version: {truth['major_minor']['value']}",
        "owner_package: docs-align",
        "---",
        "",
        "# Documentation Alignment Summary",
        "",
        "This page is generated from repository inventory, source-truth manifests, asset metadata, and the docs-alignment audit.",
        "",
        "| Signal | Value |",
        "|---|---:|",
        f"| Version | `{truth['version']['value']}` |",
        f"| Public/framework docs scanned | {inventory['counts']['docs']} |",
        f"| Shipped skills | {truth['skill_count']['value']} |",
        f"| Workflow packages | {truth['workflow_count']['value']} |",
        f"| Supported platforms | {truth['platform_count']['value']} |",
        f"| Audit findings | {audit_result['finding_count']} |",
        f"| Critical findings | {audit_result['critical_count']} |",
        f"| Major findings | {audit_result['major_count']} |",
        "",
        "## Generated Artifacts",
        "",
        "- `docs-inventory.json`: scanned docs, skills, workflows, assets, CI workflows, and CLI commands.",
        "- `docs-truth-map.json`: claims and their backing source files.",
        "- `docs-audit-result.json`: JSON-first findings for drift and Markdown/doc hygiene.",
        "- `docs-asset-manifest.json`: asset metadata and references.",
        "",
    ]
    if audit_result["findings"]:
        lines.extend(["## Findings", ""])
        for finding in audit_result["findings"][:20]:
            location = finding["path"] if finding["line"] is None else f"{finding['path']}:{finding['line']}"
            lines.append(f"- `{finding['severity']}` `{finding['category']}` {location}: {finding['message']}")
        lines.append("")
    else:
        lines.extend(["## Findings", "", "No critical or major documentation alignment findings were detected.", ""])
    path = repo_root / SUMMARY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    path.write_text(
        markdown_with_provenance(
            text,
            base_provenance(
                repo_root,
                emitter="docs-align",
                artifact_path=_artifact_id(repo_root, path),
                generated_commit_parent=True,
            ),
        ),
        encoding="utf-8",
    )


def generate_alignment_artifacts(repo_root: Path) -> dict[str, str]:
    asset_manifest = collect_asset_manifest(repo_root)
    write_assets_readme(repo_root, asset_manifest, dry_run=False)
    inventory = collect_inventory(repo_root)
    truth = collect_truth_map(repo_root)
    audit_result = audit(repo_root)
    write_summary(repo_root, inventory, audit_result)
    inventory = collect_inventory(repo_root)
    _write_json(repo_root / INVENTORY_PATH, inventory, repo_root=repo_root)
    _write_json(repo_root / TRUTH_MAP_PATH, truth, repo_root=repo_root)
    _write_json(repo_root / ASSET_MANIFEST_PATH, asset_manifest, repo_root=repo_root)
    _write_json(repo_root / AUDIT_PATH, audit_result, repo_root=repo_root)
    return {
        "inventory": str(repo_root / INVENTORY_PATH),
        "truth_map": str(repo_root / TRUTH_MAP_PATH),
        "asset_manifest": str(repo_root / ASSET_MANIFEST_PATH),
        "audit": str(repo_root / AUDIT_PATH),
        "summary": str(repo_root / SUMMARY_PATH),
        "assets_readme": str(repo_root / ASSETS_README),
    }

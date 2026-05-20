#!/usr/bin/env python3
"""Inventory, audit, and align repository documentation against source truth."""

from __future__ import annotations

import argparse
import json
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml


_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from _localsetup.core.git_subprocess import run_git
from _localsetup.core.manifests import load_pack_config, load_platforms
from _localsetup.core.provenance import json_with_provenance, markdown_with_provenance, base_provenance
from _localsetup.core.skills import load_skill_catalog, parse_skill_frontmatter, skill_taxonomy_payload
from _localsetup.core.workflows import load_workflow_catalog, workflow_catalog_payload


SCHEMA_VERSION = "1.0"
GENERATED_DIR = Path("_localsetup/docs/_generated")
SUMMARY_PATH = GENERATED_DIR / "docs-alignment-summary.md"
INVENTORY_PATH = GENERATED_DIR / "docs-inventory.json"
TRUTH_MAP_PATH = GENERATED_DIR / "docs-truth-map.json"
AUDIT_PATH = GENERATED_DIR / "docs-audit-result.json"
ASSET_MANIFEST_PATH = GENERATED_DIR / "docs-asset-manifest.json"
ASSETS_README = Path("assets/README.md")
LIFECYCLE_STATES = {"ACTIVE", "PROPOSAL", "DRAFT", "DEPRECATED", "ARCHIVED"}
LOCAL_DOC_EXCLUDES = {
    ".git",
    ".cache",
    ".codex",
    ".claude",
    ".cursor",
    ".kilo",
    ".localsetup",
    ".localsetup-maint",
    ".opencode",
    ".openclaw",
    ".pytest_cache",
    ".venv",
    ".venv-codex",
    "__pycache__",
    "localsetup.egg-info",
    "node_modules",
    "state",
}
PUBLIC_DOCS = (
    "README.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "SUPPORT.md",
    "_localsetup/README.md",
    "_localsetup/docs/README.md",
    "_localsetup/docs/QUICKSTART.md",
    "_localsetup/docs/FEATURES.md",
    "_localsetup/docs/WORKFLOW_PACKAGES.md",
    "_localsetup/docs/PLATFORM_REGISTRY.md",
)


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str
    category: str
    path: str
    line: int | None
    message: str
    expected: Any = None
    actual: Any = None
    source: str = ""
    fix_scope: str = "manual_review"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "severity": self.severity,
            "category": self.category,
            "path": self.path,
            "line": self.line,
            "message": self.message,
            "expected": self.expected,
            "actual": self.actual,
            "source": self.source,
            "fix_scope": self.fix_scope,
        }


def _repo_root(value: str | None) -> Path:
    return Path(value).expanduser().resolve() if value else _ROOT


def _rel(repo_root: Path, path: Path) -> str:
    return path.resolve().relative_to(repo_root.resolve()).as_posix()


def _artifact_id(repo_root: Path, path: Path) -> Path:
    try:
        return Path(_rel(repo_root, path))
    except ValueError:
        return path


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _write_json(path: Path, payload: dict[str, Any], *, repo_root: Path | None = None, emitter: str = "docs-align") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = payload
    if repo_root is not None:
        output = json_with_provenance(
            payload,
            base_provenance(
                repo_root,
                emitter=emitter,
                artifact_path=_artifact_id(repo_root, path),
                generated_commit_parent=True,
            ),
        )
    path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _frontmatter(text: str) -> dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}
    data = yaml.safe_load(text[4:end])
    return data if isinstance(data, dict) else {}


def _markdown_files(repo_root: Path) -> list[Path]:
    files: list[Path] = []
    candidates: list[Path]
    if (repo_root / ".git").exists():
        completed = run_git(
            repo_root,
            ["ls-files", "--cached", "--others", "--exclude-standard", "-z", "--", "*.md"],
            text=False,
            capture_output=True,
            check=False,
        )
        if completed.returncode == 0:
            candidates = [
                repo_root / raw.decode("utf-8", errors="replace")
                for raw in completed.stdout.split(b"\0")
                if raw
            ]
        else:
            candidates = sorted(repo_root.rglob("*.md"))
    else:
        candidates = sorted(repo_root.rglob("*.md"))

    for path in candidates:
        if not path.is_file():
            continue
        rel_parts = path.relative_to(repo_root).parts
        if any(part in LOCAL_DOC_EXCLUDES for part in rel_parts):
            continue
        files.append(path)
    return sorted(files)


def _classify_doc(repo_root: Path, path: Path) -> str:
    rel = _rel(repo_root, path)
    if rel.startswith("_localsetup/docs/_generated/"):
        return "generated"
    if rel.startswith("_localsetup/docs/"):
        return "framework"
    if rel in PUBLIC_DOCS or rel.startswith("docs/"):
        return "public"
    if "/SKILL.md" in rel:
        return "skill"
    return "other"


def _managed_blocks(text: str) -> list[str]:
    return sorted(set(re.findall(r"<!--\s*([A-Za-z0-9_.-]+):start\s*-->", text)))


def _png_dimensions(path: Path) -> tuple[int, int] | None:
    try:
        data = path.read_bytes()[:24]
    except OSError:
        return None
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n") and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    return None


def _svg_dimensions(path: Path) -> tuple[int, int] | None:
    text = _read_text(path)[:2048]
    viewbox = re.search(r'viewBox=["\']\s*[-0-9.]+\s+[-0-9.]+\s+([0-9.]+)\s+([0-9.]+)\s*["\']', text)
    if viewbox:
        return int(float(viewbox.group(1))), int(float(viewbox.group(2)))
    width = re.search(r'width=["\']([0-9.]+)', text)
    height = re.search(r'height=["\']([0-9.]+)', text)
    if width and height:
        return int(float(width.group(1))), int(float(height.group(1)))
    return None


def collect_asset_manifest(repo_root: Path) -> dict[str, Any]:
    assets = []
    assets_root = repo_root / "assets"
    if assets_root.is_dir():
        for path in sorted(assets_root.rglob("*")):
            if not path.is_file():
                continue
            rel = _rel(repo_root, path)
            suffix = path.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
                continue
            dims = _png_dimensions(path) if suffix == ".png" else _svg_dimensions(path) if suffix == ".svg" else None
            references = []
            for md in _markdown_files(repo_root):
                text = _read_text(md)
                for kind, target, _, _ in _markdown_links(text):
                    resolved = _resolve_markdown_target(repo_root, md, target) if kind == "image" else None
                    if resolved and resolved == path.resolve():
                        references.append(_rel(repo_root, md))
                        break
            assets.append(
                {
                    "path": rel,
                    "type": suffix.lstrip(".") or "unknown",
                    "dimensions": {"width": dims[0], "height": dims[1]} if dims else None,
                    "references": sorted(set(references)),
                    "provenance": "repository-maintained asset",
                    "license": "Repository license unless otherwise documented",
                    "alt_text_required": True,
                }
            )
    return {"schema_version": SCHEMA_VERSION, "assets": assets, "count": len(assets)}


def collect_inventory(repo_root: Path) -> dict[str, Any]:
    docs = []
    for path in _markdown_files(repo_root):
        text = _read_text(path)
        fm = _frontmatter(text)
        docs.append(
            {
                "path": _rel(repo_root, path),
                "class": _classify_doc(repo_root, path),
                "status": str(fm.get("status", "")),
                "version": str(fm.get("version", "")),
                "owner_skill": str(fm.get("owner_skill", "")),
                "owner_package": str(fm.get("owner_package", "")),
                "managed_blocks": _managed_blocks(text),
                "has_frontmatter": bool(fm),
            }
        )

    pack = load_pack_config(repo_root)
    platforms = load_platforms(repo_root)
    skills = load_skill_catalog(repo_root)
    workflows = load_workflow_catalog(repo_root)
    commands = sorted(set(re.findall(r'sub\.add_parser\("([^"]+)"', _read_text(repo_root / "_localsetup/core/cli.py"))))
    ci = sorted(_rel(repo_root, path) for path in (repo_root / ".github/workflows").glob("*.yml"))
    ci.extend(sorted(_rel(repo_root, path) for path in (repo_root / ".github/workflows").glob("*.yaml")))

    return {
        "schema_version": SCHEMA_VERSION,
        "repo": ".",
        "docs": docs,
        "counts": {
            "docs": len(docs),
            "public_docs": sum(1 for row in docs if row["class"] == "public"),
            "framework_docs": sum(1 for row in docs if row["class"] == "framework"),
            "generated_docs": sum(1 for row in docs if row["class"] == "generated"),
            "skills": len(skills),
            "workflows": len(workflows),
            "platforms": len(platforms),
            "workflow_packs": sum(len(items) for items in pack.workflow_packs.values()),
        },
        "skills": [
            {
                "name": skill.name,
                "path": _rel(repo_root, skill.path),
                "packs": skill.packs,
                "class": skill.taxonomy_class,
                "sort_priority": skill.sort_priority,
                "tags": skill.tags,
                "owner_scope": skill.owner_scope,
            }
            for skill in skills
        ],
        "workflows": [
            {
                "package": workflow.package,
                "workflow_id": workflow.workflow_id,
                "path": _rel(repo_root, workflow.path),
                "packs": workflow.packs,
            }
            for workflow in workflows
        ],
        "platforms": [{"id": platform.platform_id, "repo_paths": platform.repo_paths} for platform in platforms],
        "assets": collect_asset_manifest(repo_root)["assets"],
        "ci_workflows": ci,
        "cli_commands": commands,
    }


def collect_truth_map(repo_root: Path) -> dict[str, Any]:
    version = _read_text(repo_root / "VERSION").strip()
    pyproject = _read_text(repo_root / "pyproject.toml") if (repo_root / "pyproject.toml").exists() else ""
    pyproject_version = ""
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', pyproject)
    if match:
        pyproject_version = match.group(1)
    facts_path = repo_root / GENERATED_DIR / "facts.json"
    facts = json.loads(_read_text(facts_path)) if facts_path.exists() else {}
    taxonomy_path = repo_root / GENERATED_DIR / "skill-taxonomy.json"
    generated_skill_taxonomy = json.loads(_read_text(taxonomy_path)) if taxonomy_path.exists() else {}
    platforms = load_platforms(repo_root)
    skills = load_skill_catalog(repo_root)
    workflows = load_workflow_catalog(repo_root)
    active_doc_owners = [
        {
            "path": row["path"],
            "owner_skill": row["owner_skill"],
            "owner_package": row["owner_package"],
        }
        for row in collect_inventory(repo_root)["docs"]
        if row["class"] == "framework" and row["status"] == "ACTIVE"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "truths": {
            "version": {
                "value": version,
                "sources": ["VERSION", "pyproject.toml", "_localsetup/docs/_generated/facts.json"],
                "pyproject_version": pyproject_version,
                "facts_version": facts.get("version", ""),
            },
            "major_minor": {
                "value": ".".join(version.split(".")[:2]) if "." in version else version,
                "sources": ["VERSION"],
            },
            "platform_count": {
                "value": len(platforms),
                "sources": ["_localsetup/config/platforms.yaml"],
            },
            "skill_count": {
                "value": len(skills),
                "sources": ["_localsetup/skills/ls-*/SKILL.md", "_localsetup/config/pack.yaml"],
            },
            "skill_taxonomy": {
                "value": skill_taxonomy_payload(repo_root),
                "sources": ["_localsetup/config/pack.yaml", "_localsetup/skills/ls-*/SKILL.md"],
            },
            "workflow_count": {
                "value": len(workflows),
                "sources": ["_localsetup/workflows/ls-workflow-*/workflow.yaml"],
            },
            "workflow_catalog": {
                "value": workflow_catalog_payload(repo_root),
                "sources": ["_localsetup/workflows/*/workflow.yaml"],
            },
            "active_doc_owners": {
                "value": active_doc_owners,
                "sources": ["_localsetup/docs/**/*.md frontmatter"],
            },
        },
        "generated_facts": facts,
        "generated_skill_taxonomy": generated_skill_taxonomy,
    }


def _line_for_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_external(target: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)) or target.startswith("#")


def _resolve_markdown_target(repo_root: Path, source: Path, target: str) -> Path | None:
    clean = target.split("#", 1)[0].strip()
    if not clean or _is_external(clean):
        return None
    clean = clean.replace("%20", " ")
    if clean.startswith("/"):
        candidates = [(repo_root / clean.lstrip("/")).resolve()]
    else:
        candidates = [(source.parent / clean).resolve()]
    for candidate in candidates:
        try:
            candidate.relative_to(repo_root)
        except ValueError:
            continue
        if candidate.exists():
            return candidate
    for candidate in candidates:
        try:
            candidate.relative_to(repo_root)
            return candidate
        except ValueError:
            continue
    return None


def _markdown_links(text: str) -> Iterable[tuple[str, str, int, str]]:
    for match in re.finditer(r"!\[([^\]]*)\]\(([^)]+)\)", text):
        yield "image", match.group(2).strip(), match.start(), match.group(1).strip()
    for match in re.finditer(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)", text):
        yield "link", match.group(2).strip(), match.start(), match.group(1).strip()
    for match in re.finditer(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"'][^>]*>", text, flags=re.IGNORECASE):
        alt = re.search(r"\balt=[\"']([^\"']*)[\"']", match.group(0), flags=re.IGNORECASE)
        yield "image", match.group(1).strip(), match.start(), alt.group(1).strip() if alt else ""


def audit(repo_root: Path) -> dict[str, Any]:
    truth = collect_truth_map(repo_root)
    facts = truth["generated_facts"]
    generated_skill_taxonomy = truth["generated_skill_taxonomy"]
    truths = truth["truths"]
    skill_count = truths["skill_count"]["value"]
    workflow_count = truths["workflow_count"]["value"]
    version = truths["version"]["value"]
    valid_owner_skills = {skill.name for skill in load_skill_catalog(repo_root)}
    valid_owner_packages = {workflow.package for workflow in load_workflow_catalog(repo_root)} | {"generate-docs", "docs-align"}
    findings: list[Finding] = []

    if truths["version"]["pyproject_version"] and truths["version"]["pyproject_version"] != version:
        findings.append(Finding("version.pyproject", "critical", "version_drift", "pyproject.toml", None, "pyproject version does not match VERSION", version, truths["version"]["pyproject_version"], "VERSION", "generated"))
    if facts:
        for key, expected in (("version", version), ("skill_count", skill_count), ("workflow_count", workflow_count), ("platform_count", truths["platform_count"]["value"])):
            actual = facts.get(key)
            if actual != expected:
                findings.append(Finding(f"facts.{key}", "critical", "generated_drift", "_localsetup/docs/_generated/facts.json", None, f"generated facts `{key}` is stale", expected, actual, "live manifests", "generated"))
    expected_skill_taxonomy = truths["skill_taxonomy"]["value"]
    if generated_skill_taxonomy:
        actual_skill_taxonomy = {k: v for k, v in generated_skill_taxonomy.items() if k != "provenance"}
        if actual_skill_taxonomy != expected_skill_taxonomy:
            findings.append(Finding("skill_taxonomy.generated", "critical", "generated_drift", "_localsetup/docs/_generated/skill-taxonomy.json", None, "generated skill taxonomy is stale", expected_skill_taxonomy, actual_skill_taxonomy, "live skill taxonomy", "generated"))
    else:
        findings.append(Finding("skill_taxonomy.missing", "critical", "generated_drift", "_localsetup/docs/_generated/skill-taxonomy.json", None, "generated skill taxonomy is missing", expected_skill_taxonomy, None, "live skill taxonomy", "generated"))

    count_re = re.compile(r"\b(\d+)\s+shipped(?:\s+capability)?\s+skills?\s+plus\s+(\d+)\s+(?:first-class\s+)?workflow\s+packages\b", re.IGNORECASE)
    for path in _markdown_files(repo_root):
        rel = _rel(repo_root, path)
        text = _read_text(path)
        for match in count_re.finditer(text):
            actual = {"skills": int(match.group(1)), "workflows": int(match.group(2))}
            expected = {"skills": skill_count, "workflows": workflow_count}
            if actual != expected:
                findings.append(Finding(f"count.{rel}:{_line_for_offset(text, match.start())}", "major", "stale_count", rel, _line_for_offset(text, match.start()), "hard-coded shipped skill/workflow count is stale", expected, actual, "live skill/workflow manifests", "public"))

        if text.count("```") % 2:
            findings.append(Finding(f"fence.{rel}", "major", "markdown", rel, None, "unclosed fenced code block", "even fence count", "odd fence count", rel, "public"))

        if rel.startswith("_localsetup/docs/") and not rel.startswith("_localsetup/docs/_generated/") and "/local-context/" not in rel:
            fm = _frontmatter(text)
            if fm.get("status") not in LIFECYCLE_STATES or not fm.get("version"):
                findings.append(Finding(f"lifecycle.{rel}", "major", "lifecycle", rel, 1, "framework doc is missing valid lifecycle status/version frontmatter", "status and version", fm, "docs.config.yaml", "public"))
            if fm.get("status") == "ACTIVE":
                owner_skill = str(fm.get("owner_skill", "")).strip()
                owner_package = str(fm.get("owner_package", "")).strip()
                if not owner_skill and not owner_package:
                    findings.append(Finding(f"ownership.{rel}", "major", "ownership", rel, 1, "active framework doc is missing owner_skill or owner_package frontmatter", "owner_skill or owner_package", fm, "skill-owned documentation policy", "public"))
                if owner_skill and owner_skill not in valid_owner_skills:
                    findings.append(Finding(f"ownership_skill.{rel}", "major", "ownership", rel, 1, "active framework doc references missing owner_skill", sorted(valid_owner_skills), owner_skill, "skill catalog", "public"))
                if owner_package and owner_package not in valid_owner_packages:
                    findings.append(Finding(f"ownership_package.{rel}", "major", "ownership", rel, 1, "active framework doc references missing owner_package", sorted(valid_owner_packages), owner_package, "workflow catalog and generated packages", "public"))

        for kind, target, offset, label in _markdown_links(text):
            line = _line_for_offset(text, offset)
            if kind == "image" and not label:
                findings.append(Finding(f"image_alt.{rel}:{line}", "minor", "asset", rel, line, "image is missing non-empty alt text", "non-empty alt text", label, "GitHub Markdown guidance", "public"))
            resolved = _resolve_markdown_target(repo_root, path, target)
            if resolved and not resolved.exists():
                findings.append(Finding(f"link.{rel}:{line}", "major", "link", rel, line, f"relative {kind} target does not exist: {target}", "existing path", target, rel, "public"))

    for rel in ("README.md", "_localsetup/docs/README.md", "_localsetup/docs/FEATURES.md"):
        path = repo_root / rel
        if path.exists() and "facts-block:start" not in _read_text(path):
            findings.append(Finding(f"managed_block.{rel}", "major", "generated_block", rel, None, "missing generated facts block", "facts-block", None, "_localsetup/docs/_generated/facts.json", "generated"))

    assets_readme = repo_root / ASSETS_README
    expected_assets_readme = build_assets_readme_text(collect_asset_manifest(repo_root))
    actual_assets_readme = _read_text(assets_readme) if assets_readme.exists() else ""
    if actual_assets_readme != expected_assets_readme:
        findings.append(
            Finding(
                "asset_readme.drift",
                "major",
                "asset",
                str(ASSETS_README),
                None,
                "asset README is stale relative to the generated asset manifest",
                "current generated asset README",
                "missing or stale asset README",
                "assets/* and markdown image references",
                "assets",
            )
        )

    findings_dict = [finding.as_dict() for finding in findings]
    severity_rank = {"critical": 4, "major": 3, "minor": 2, "info": 1}
    findings_dict.sort(key=lambda row: (-severity_rank.get(str(row["severity"]), 0), row["path"], row["id"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "ok": not any(row["severity"] in {"critical", "major"} for row in findings_dict),
        "finding_count": len(findings_dict),
        "critical_count": sum(1 for row in findings_dict if row["severity"] == "critical"),
        "major_count": sum(1 for row in findings_dict if row["severity"] == "major"),
        "minor_count": sum(1 for row in findings_dict if row["severity"] == "minor"),
        "findings": findings_dict,
    }


def build_plan(audit_result: dict[str, Any]) -> dict[str, Any]:
    buckets = {
        "generated_fixes": [],
        "public_doc_rewrites": [],
        "lifecycle_cleanup": [],
        "asset_cleanup": [],
        "ownership_cleanup": [],
        "ci_changes": [],
        "manual_review": [],
    }
    for finding in audit_result["findings"]:
        category = finding["category"]
        if finding["fix_scope"] == "generated":
            buckets["generated_fixes"].append(finding["id"])
        elif category == "stale_count":
            buckets["public_doc_rewrites"].append(finding["id"])
        elif category == "lifecycle":
            buckets["lifecycle_cleanup"].append(finding["id"])
        elif category == "asset":
            buckets["asset_cleanup"].append(finding["id"])
        elif category == "ownership":
            buckets["ownership_cleanup"].append(finding["id"])
        else:
            buckets["manual_review"].append(finding["id"])
    return {"schema_version": SCHEMA_VERSION, "ok": audit_result["ok"], "buckets": buckets}


def _replace_managed_public_counts(repo_root: Path, dry_run: bool) -> list[str]:
    truth = collect_truth_map(repo_root)["truths"]
    skill_count = truth["skill_count"]["value"]
    workflow_count = truth["workflow_count"]["value"]
    replacements = {
        "README.md": (
            re.compile(r"\b\d+\s+shipped capability skills plus \d+\s+first-class workflow packages\b"),
            f"{skill_count} shipped capability skills plus {workflow_count} first-class workflow packages",
        ),
        "_localsetup/docs/FEATURES.md": (
            re.compile(r"\|\s*\d+\s+shipped skills plus \d+\s+workflow packages\s*\|"),
            f"| {skill_count} shipped skills plus {workflow_count} workflow packages |",
        ),
        "_localsetup/docs/PLATFORM_REGISTRY.md": (
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


def write_assets_readme(repo_root: Path, manifest: dict[str, Any], *, dry_run: bool) -> bool:
    text = build_assets_readme_text(manifest)
    path = repo_root / ASSETS_README
    before = _read_text(path) if path.exists() else ""
    if before == text:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return True


def build_assets_readme_text(manifest: dict[str, Any]) -> str:
    lines = [
        "# Asset Inventory",
        "",
        "This file is maintained by `_localsetup/tools/docs_alignment.py apply --scope assets` and the generated-doc refresh.",
        "",
        "| Asset | Type | Dimensions | References | Notes |",
        "|---|---|---|---|---|",
    ]
    for asset in manifest["assets"]:
        dims = asset["dimensions"]
        dim_text = f"{dims['width']}x{dims['height']}" if dims else "unknown"
        refs = ", ".join(f"`{ref}`" for ref in asset["references"]) or "none found"
        lines.append(f"| `{asset['path']}` | {asset['type']} | {dim_text} | {refs} | {asset['license']} |")
    lines.append("")
    return "\n".join(lines) + "\n"


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


if __name__ == "__main__":
    raise SystemExit(main())

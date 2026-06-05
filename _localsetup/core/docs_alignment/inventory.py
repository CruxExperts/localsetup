from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _localsetup.core.manifests import load_pack_config, load_platforms
from _localsetup.core.skills import load_skill_catalog, skill_taxonomy_payload
from _localsetup.core.workflows import load_workflow_catalog, workflow_catalog_payload

from .assets import collect_asset_manifest
from .constants import GENERATED_DIR, SCHEMA_VERSION
from .io import _classify_doc, _frontmatter, _managed_blocks, _markdown_files, _read_text, _rel

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

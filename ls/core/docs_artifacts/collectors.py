from __future__ import annotations

from pathlib import Path
from typing import Any

from ls.core.client_registry import load_client_registry, platform_rows
from ls.core.skills import load_skill_catalog
from ls.core.workflows import load_workflow_catalog

from .common import ascii_clean


def collect_skills(repo_root: Path) -> list[dict[str, Any]]:
    skills = []
    for skill in load_skill_catalog(repo_root):
        skill_md = skill.path / "SKILL.md"
        description = ascii_clean(skill.description.replace("\n", " ").strip())
        skills.append(
            {
                "id": skill.name,
                "name": skill.name,
                "description": description,
                "version": skill.version,
                "path": str(skill_md.relative_to(repo_root)),
                "class": skill.taxonomy_class,
                "sort_priority": skill.sort_priority,
                "tags": skill.tags,
                "owner_scope": skill.owner_scope,
                "packs": skill.packs,
            }
        )
    return skills


def collect_workflows(repo_root: Path) -> list[dict[str, Any]]:
    workflows = []
    for workflow in load_workflow_catalog(repo_root):
        workflows.append(
            {
                "id": workflow.workflow_id,
                "package": workflow.package,
                "name": workflow.display_name,
                "description": ascii_clean(workflow.description.replace("\n", " ").strip()),
                "aliases": workflow.aliases,
                "required_skills": workflow.required_skills,
                "required_tools": workflow.required_tools,
                "required_docs": workflow.required_docs,
                "packs": workflow.packs,
                "path": str((workflow.path / "SKILL.md").relative_to(repo_root)),
            }
        )
    return workflows


def collect_platforms(repo_root: Path) -> list[dict[str, str]]:
    registry = load_client_registry(repo_root)
    variants_by_platform = {
        str(variant.data["compatibility"]["platform_id"]): variant
        for variant in registry.variants()
        if variant.data.get("compatibility")
    }
    rows = []
    for projected in platform_rows(registry):
        platform_id = str(projected["id"])
        variant = variants_by_platform[platform_id]
        rows.append(
            {
                "id": platform_id,
                "display_name": str(variant.data["display_name"]),
                "context_loader": ", ".join(variant.data["policy"]["repo"].get("paths", [])),
                "skills_path": ", ".join(projected["repo_paths"]),
            }
        )
    return rows

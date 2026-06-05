from __future__ import annotations

from pathlib import Path
from typing import Any

from _localsetup.core.skills import load_skill_catalog
from _localsetup.core.workflows import load_workflow_catalog

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


def collect_platforms(platform_registry: Path) -> list[dict[str, str]]:
    rows = []
    in_supported_platforms = False
    for line in platform_registry.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("##"):
            in_supported_platforms = stripped.startswith("## Supported platforms")
            continue
        if not in_supported_platforms:
            continue
        if not line.startswith("|"):
            continue
        if stripped.startswith("| ID ") or stripped.startswith("|----"):
            continue
        parts = [p.strip() for p in line.strip("|").split("|")]
        if len(parts) != 4:
            continue
        platform_id, display, context_loader, skills_path = parts
        if not platform_id:
            continue
        rows.append(
            {
                "id": platform_id,
                "display_name": display,
                "context_loader": context_loader,
                "skills_path": skills_path,
            }
        )
    return rows

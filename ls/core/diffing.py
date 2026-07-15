from __future__ import annotations

from pathlib import Path
from typing import Any

from .lockfile import load_json
from .manifests import load_pack_config
from .paths import repo_path, target_lockfile_path
from .plan import build_install_plan


def diff_plan_current(
    repo_root: Path,
    *,
    home: Path,
    packs: list[str] | None,
    platform_ids: list[str] | None,
    target_root: Path | None,
    attach_mode: str,
    preset: str | None = None,
    skills: list[str] | None = None,
    skill_classes: list[str] | None = None,
    skill_tags: list[str] | None = None,
    exclude_skills: list[str] | None = None,
    workflows: list[str] | None = None,
    global_packs: list[str] | None = None,
    global_preset: str | None = None,
    global_skills: list[str] | None = None,
    global_skill_classes: list[str] | None = None,
    global_skill_tags: list[str] | None = None,
    global_exclude_skills: list[str] | None = None,
    global_workflows: list[str] | None = None,
    repo_packs: list[str] | None = None,
    repo_preset: str | None = None,
    repo_skills: list[str] | None = None,
    repo_skill_classes: list[str] | None = None,
    repo_skill_tags: list[str] | None = None,
    repo_exclude_skills: list[str] | None = None,
    repo_workflows: list[str] | None = None,
) -> dict[str, Any]:
    plan = build_install_plan(
        repo_root,
        home=home,
        packs=packs,
        preset=preset,
        skills=skills,
        workflows=workflows,
        skill_classes=skill_classes,
        skill_tags=skill_tags,
        exclude_skills=exclude_skills,
        global_packs=global_packs,
        global_preset=global_preset,
        global_skills=global_skills,
        global_workflows=global_workflows,
        global_skill_classes=global_skill_classes,
        global_skill_tags=global_skill_tags,
        global_exclude_skills=global_exclude_skills,
        repo_packs=repo_packs,
        repo_preset=repo_preset,
        repo_skills=repo_skills,
        repo_workflows=repo_workflows,
        repo_skill_classes=repo_skill_classes,
        repo_skill_tags=repo_skill_tags,
        repo_exclude_skills=repo_exclude_skills,
        platform_ids=platform_ids,
        target_root=target_root,
        attach_mode=attach_mode,
    )
    attachment_root = target_root or repo_root
    pack = load_pack_config(repo_root)
    lock_path = repo_path(attachment_root, pack.lockfile, "repo.lockfile")
    if lock_path.name != "lock.json" or lock_path.parent.name != ".localsetup":
        lock_path = target_lockfile_path(attachment_root)
    lock = load_json(lock_path)
    planned_skills = set(plan.rollback_metadata.get("skills", []))
    planned_workflows = set(plan.rollback_metadata.get("workflows", []))
    current_skills = {Path(path).name for path in lock.get("installed_skills", [])}
    current_workflows = {Path(path).name for path in lock.get("installed_workflows", [])}
    planned_adapters = {str(action.path) for action in plan.actions if action.kind == "attach_repo_path"}
    current_adapters = {str(item.get("path")) for item in lock.get("adapter_targets", [])}
    return {
        "skills": {"added": sorted(planned_skills - current_skills), "removed": sorted(current_skills - planned_skills), "unchanged": sorted(planned_skills & current_skills)},
        "workflows": {"added": sorted(planned_workflows - current_workflows), "removed": sorted(current_workflows - planned_workflows), "unchanged": sorted(planned_workflows & current_workflows)},
        "adapters": {"added": sorted(planned_adapters - current_adapters), "removed": sorted(current_adapters - planned_adapters), "unchanged": sorted(planned_adapters & current_adapters)},
        "has_lockfile": bool(lock),
    }

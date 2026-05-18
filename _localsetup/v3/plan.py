from __future__ import annotations

from pathlib import Path

from .aliases import collect_skill_aliases, legacy_skill_name
from .adapters import adapter_targets, validate_platform_selectors
from .manifests import load_pack_config, load_platforms
from .models import DeployPlan, PlanAction
from .paths import expand_user_path
from .selection import resolve_package_selection


def build_install_plan(
    repo_root: Path,
    home: Path,
    packs: list[str] | None = None,
    preset: str | None = None,
    skills: list[str] | None = None,
    skill_classes: list[str] | None = None,
    skill_tags: list[str] | None = None,
    exclude_skills: list[str] | None = None,
    attach_mode: str = "symlink",
    platform_ids: list[str] | None = None,
    target_root: Path | None = None,
) -> DeployPlan:
    if attach_mode not in {"symlink", "portable"}:
        raise ValueError(f"unsupported attach mode: {attach_mode}")

    pack = load_pack_config(repo_root)
    platforms = load_platforms(repo_root)
    validate_platform_selectors(repo_root, platform_ids)
    selected_ids = set(platform_ids or [])
    selected_platforms = [p for p in platforms if p.platform_id in selected_ids]
    attachment_root = target_root or repo_root
    global_root = expand_user_path(pack.global_root, home)

    selection = resolve_package_selection(
        repo_root,
        packs=packs,
        preset=preset,
        skills=skills,
        skill_classes=skill_classes,
        skill_tags=skill_tags,
        exclude_skills=exclude_skills,
        target_root=attachment_root,
    )
    selected_names = selection.skills
    selected_workflows = selection.workflows
    legacy_aliases = collect_skill_aliases(repo_root / "_localsetup" / "skills")
    selected_aliases = {legacy_skill_name(name): name for name in selected_names}
    actions: list[PlanAction] = [
        PlanAction("ensure_dir", global_root),
        PlanAction("write_registry", expand_user_path(pack.global_registry, home), {"pack_id": pack.pack_id}),
        PlanAction("install_skills", global_root, {"skills": selected_names}),
    ]
    if selected_workflows:
        actions.append(PlanAction("install_workflows", global_root, {"workflows": selected_workflows}))

    for target in adapter_targets(repo_root, home, platform_ids=platform_ids, target_root=attachment_root):
        actions.append(
            PlanAction(
                "attach_repo_path",
                target["repo_path"],
                {
                    "platform": target["platform"],
                    "mode": attach_mode,
                    "global_root": str(global_root),
                    "packages": selection.packages,
                },
            )
        )

    rollback = {
        "created_paths": [str(global_root)],
        "repo_links": [str(a.path) for a in actions if a.kind == "attach_repo_path"],
        "preset": selection.preset,
        "packs": selection.packs,
        "selectors": selection.selectors,
        "platforms": [platform.platform_id for platform in selected_platforms],
        "target_root": str(attachment_root),
        "global_only": not selected_platforms,
        "attach_mode": attach_mode,
        "aliases": selected_aliases,
        "catalog_aliases": legacy_aliases,
        "skills": selected_names,
        "workflows": selected_workflows,
        "packages": selection.packages,
    }
    return DeployPlan(actions=actions, rollback_metadata=rollback)

from __future__ import annotations

from pathlib import Path

from .aliases import collect_skill_aliases
from .adapters import adapter_targets, validate_platform_selectors
from .manifests import load_pack_config, load_platforms
from .models import DeployPlan, PlanAction
from .paths import expand_user_path
from .skills import selected_skill_names


def build_install_plan(
    repo_root: Path,
    home: Path,
    packs: list[str] | None = None,
    attach_mode: str = "symlink",
    platform_ids: list[str] | None = None,
) -> DeployPlan:
    if attach_mode not in {"symlink", "portable"}:
        raise ValueError(f"unsupported attach mode: {attach_mode}")

    pack = load_pack_config(repo_root)
    platforms = load_platforms(repo_root)
    validate_platform_selectors(repo_root, platform_ids)
    selected_platforms = [p for p in platforms if not platform_ids or p.platform_id in platform_ids]
    global_root = expand_user_path(pack.global_root, home)

    all_aliases = collect_skill_aliases(repo_root / "_localsetup" / "skills")
    selected_names = selected_skill_names(repo_root, packs)
    install_aliases = {name: all_aliases[name] for name in selected_names}
    actions: list[PlanAction] = [
        PlanAction("ensure_dir", global_root),
        PlanAction("write_registry", expand_user_path(pack.global_registry, home), {"pack_id": pack.pack_id}),
        PlanAction("install_skills", global_root, {"aliases": install_aliases}),
    ]

    for target in adapter_targets(repo_root, home, platform_ids=platform_ids):
        actions.append(
            PlanAction(
                "attach_repo_path",
                target["repo_path"],
                {"platform": target["platform"], "mode": attach_mode, "global_root": str(global_root)},
            )
        )

    rollback = {
        "created_paths": [str(global_root)],
        "repo_links": [str(a.path) for a in actions if a.kind == "attach_repo_path"],
        "packs": packs or ["core"],
        "platforms": [platform.platform_id for platform in selected_platforms],
        "attach_mode": attach_mode,
        "aliases": install_aliases,
        "catalog_aliases": all_aliases,
    }
    return DeployPlan(actions=actions, rollback_metadata=rollback)

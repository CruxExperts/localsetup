from __future__ import annotations

from pathlib import Path

from .provenance import load_package_marker, marker_public_snapshot
from .source import source_commit


def build_lock_payload(
    *,
    repo_root: Path,
    home: Path,
    attachment_root: Path,
    pack,
    plan,
    installed_skills: list[str],
    installed_workflows: list[str],
    installed_codex_agents: list[str],
    dependency_info: dict | None,
) -> dict:
    adapter_actions = [action for action in plan.actions if action.kind == "attach_repo_path"]
    return {
        "version": 2,
        "pack": pack.pack_id,
        "namespace": pack.namespace,
        "source_commit": source_commit(repo_root),
        "source_root": str(repo_root),
        "localsetup_home": str(home / ".local" / "share" / "localsetup"),
        "target_root": str(attachment_root),
        "aliases": plan.rollback_metadata.get("aliases", {}),
        "skills": plan.rollback_metadata.get("skills", []),
        "workflows": plan.rollback_metadata.get("workflows", []),
        "codex_agents": plan.rollback_metadata.get("codex_agents", []),
        "global_baseline_selectors": plan.rollback_metadata.get("global_baseline_selectors", {}),
        "global_baseline_packs": plan.rollback_metadata.get("global_baseline_packs", []),
        "global_baseline_skills": plan.rollback_metadata.get("global_baseline_skills", []),
        "global_baseline_workflows": plan.rollback_metadata.get("global_baseline_workflows", []),
        "global_baseline_packages": plan.rollback_metadata.get("global_baseline_packages", []),
        "repo_selectors": plan.rollback_metadata.get("repo_selectors", {}),
        "repo_packs": plan.rollback_metadata.get("repo_packs", []),
        "repo_skills": plan.rollback_metadata.get("repo_skills", []),
        "repo_workflows": plan.rollback_metadata.get("repo_workflows", []),
        "repo_packages": plan.rollback_metadata.get("repo_packages", []),
        "adapter_state": [state for state in plan.rollback_metadata.get("repo_links", [])],
        "adapter_targets": [
            {
                "platform": action.details.get("platform"),
                "path": str(action.path),
                "mode": action.details.get("mode", "symlink"),
                "global_root": action.details.get("global_root"),
                "packages": action.details.get("packages", []),
            }
            for action in adapter_actions
        ],
        "platforms": plan.rollback_metadata.get("platforms", []),
        "global_only": plan.rollback_metadata.get("global_only", False),
        "attach_mode": plan.rollback_metadata.get("attach_mode", "symlink"),
        "installed_skills": installed_skills,
        "installed_workflows": installed_workflows,
        "installed_codex_agents": installed_codex_agents,
        "adapter_packages": plan.rollback_metadata.get("adapter_packages", []),
        "dependency_mode": (dependency_info or {}).get("mode"),
        "python_interpreter": (dependency_info or {}).get("interpreter"),
        "dependency_state": (dependency_info or {}).get("lock"),
        "package_provenance": {
            Path(path).name: marker_public_snapshot(load_package_marker(Path(path)))
            for path in [*installed_skills, *installed_workflows]
        },
    }

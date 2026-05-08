from __future__ import annotations

from pathlib import Path

from .manifests import load_platforms
from .paths import expand_user_path, repo_path


def validate_platform_selectors(repo_root: Path, platform_ids: list[str] | None) -> list[str]:
    platforms = load_platforms(repo_root)
    known_ids = {platform.platform_id for platform in platforms}
    requested_ids = set(platform_ids or [])
    unknown_ids = sorted(requested_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"unknown platform selector(s): {', '.join(unknown_ids)}")
    return sorted(requested_ids)


def adapter_targets(repo_root: Path, home: Path, platform_ids: list[str] | None = None) -> list[dict]:
    validate_platform_selectors(repo_root, platform_ids)
    selected = set(platform_ids or [])
    targets: list[dict] = []
    for platform in load_platforms(repo_root):
        if selected and platform.platform_id not in selected:
            continue
        for rel in platform.repo_paths:
            targets.append(
                {
                    "platform": platform.platform_id,
                    "repo_path": repo_path(repo_root, rel, f"{platform.platform_id}.repo_paths"),
                    "global_paths": [expand_user_path(path, home) for path in platform.global_paths],
                    "verify_rules": platform.verify_rules,
                    "rollback_targets": [
                        repo_path(repo_root, path, f"{platform.platform_id}.rollback_targets")
                        for path in platform.rollback_targets
                    ],
                }
            )
    return targets


def adapter_status(
    repo_root: Path,
    home: Path,
    global_root: Path,
    platform_ids: list[str] | None = None,
) -> list[dict]:
    status: list[dict] = []
    for target in adapter_targets(repo_root, home, platform_ids=platform_ids):
        repo_path = target["repo_path"]
        status.append(
            {
                "platform": target["platform"],
                "repo_path": str(repo_path),
                "exists": repo_path.exists() or repo_path.is_symlink(),
                "is_symlink": repo_path.is_symlink(),
                "points_to_global": repo_path.is_symlink() and repo_path.resolve() == global_root.resolve(),
                "is_portable_copy": repo_path.is_dir()
                and not repo_path.is_symlink()
                and (repo_path / ".localsetup-portable").exists(),
                "verify_rules": target["verify_rules"],
            }
        )
    return status

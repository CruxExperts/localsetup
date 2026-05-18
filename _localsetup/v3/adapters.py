from __future__ import annotations

from pathlib import Path

from .manifests import load_platforms
from .paths import expand_user_path, repo_path

ADAPTER_MARKER_JSON = ".localsetup-adapter.json"


def validate_platform_selectors(repo_root: Path, platform_ids: list[str] | None) -> list[str]:
    platforms = load_platforms(repo_root)
    known_ids = {platform.platform_id for platform in platforms}
    requested_ids = set(platform_ids or [])
    unknown_ids = sorted(requested_ids - known_ids)
    if unknown_ids:
        raise ValueError(f"unknown platform selector(s): {', '.join(unknown_ids)}")
    return sorted(requested_ids)


def adapter_targets(
    repo_root: Path,
    home: Path,
    platform_ids: list[str] | None = None,
    *,
    target_root: Path | None = None,
) -> list[dict]:
    validate_platform_selectors(repo_root, platform_ids)
    selected = set(platform_ids or [])
    if not selected:
        return []
    attachment_root = target_root or repo_root
    targets: list[dict] = []
    for platform in load_platforms(repo_root):
        if platform.platform_id not in selected:
            continue
        for rel in platform.repo_paths:
            targets.append(
                {
                    "platform": platform.platform_id,
                    "repo_path": repo_path(attachment_root, rel, f"{platform.platform_id}.repo_paths"),
                    "global_paths": [expand_user_path(path, home) for path in platform.global_paths],
                    "verify_rules": platform.verify_rules,
                    "rollback_targets": [
                        repo_path(attachment_root, path, f"{platform.platform_id}.rollback_targets")
                        for path in platform.rollback_targets
                    ],
                }
            )
    return targets


def legacy_global_roots(home: Path) -> list[Path]:
    return [home / ".local" / "share" / "agents" / "skills" / "localsetup"]


def _symlink_target(repo_path: Path) -> Path | None:
    if not repo_path.is_symlink():
        return None
    link_target = repo_path.readlink()
    if not link_target.is_absolute():
        link_target = repo_path.parent / link_target
    return link_target.resolve(strict=False)


def _visible_adapter_packages(repo_path: Path, global_root: Path) -> list[str]:
    if repo_path.is_symlink() and _symlink_target(repo_path) == global_root.resolve(strict=False):
        if global_root.exists():
            return sorted(path.name for path in global_root.iterdir() if path.is_dir())
        return []
    if not repo_path.is_dir() or repo_path.is_symlink():
        return []
    names: list[str] = []
    for child in sorted(repo_path.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_symlink() or child.is_dir():
            names.append(child.name)
    return names


def adapter_path_state(repo_path: Path, global_root: Path, *, known_global_roots: list[Path] | None = None) -> dict:
    managed_roots = [global_root, *(known_global_roots or [])]
    resolved_roots = {root.resolve(strict=False) for root in managed_roots}
    exists = repo_path.exists() or repo_path.is_symlink()
    is_symlink = repo_path.is_symlink()
    is_dangling_symlink = is_symlink and not repo_path.exists()
    points_to_global = False
    points_to_legacy_global = False
    is_monolithic_global_symlink = False
    if is_symlink:
        link_target = _symlink_target(repo_path)
        points_to_global = link_target == global_root.resolve(strict=False)
        points_to_legacy_global = bool(link_target and link_target in (resolved_roots - {global_root.resolve(strict=False)}))
        is_monolithic_global_symlink = bool(link_target and link_target in resolved_roots)
    is_scoped_symlink_adapter = (
        repo_path.is_dir()
        and not is_symlink
        and (repo_path / ADAPTER_MARKER_JSON).exists()
    )
    is_portable_copy = (
        repo_path.is_dir()
        and not is_symlink
        and (repo_path / ".localsetup-portable").exists()
    )
    is_unmanaged_directory = repo_path.is_dir() and not is_symlink and not is_portable_copy and not is_scoped_symlink_adapter
    is_regular_file = repo_path.exists() and repo_path.is_file() and not is_symlink
    is_other = repo_path.exists() and not (
        repo_path.is_file() or repo_path.is_dir() or is_symlink
    )
    collision_reason = None
    if is_dangling_symlink:
        collision_reason = "dangling symlink"
    elif is_symlink and not is_monolithic_global_symlink:
        collision_reason = "symlink points outside managed library"
    elif is_regular_file:
        collision_reason = "regular file"
    elif is_unmanaged_directory:
        collision_reason = "unmanaged adapter directory"
    elif is_other:
        collision_reason = "unsupported filesystem node"
    return {
        "exists": exists,
        "is_symlink": is_symlink,
        "is_dangling_symlink": is_dangling_symlink,
        "points_to_global": points_to_global,
        "points_to_legacy_global": points_to_legacy_global,
        "is_monolithic_global_symlink": is_monolithic_global_symlink,
        "is_scoped_symlink_adapter": is_scoped_symlink_adapter,
        "is_portable_copy": is_portable_copy,
        "is_unmanaged_directory": is_unmanaged_directory,
        "is_regular_file": is_regular_file,
        "is_other": is_other,
        "collision_reason": collision_reason,
        "visible_packages": _visible_adapter_packages(repo_path, global_root),
    }


def adapter_status(
    repo_root: Path,
    home: Path,
    global_root: Path,
    platform_ids: list[str] | None = None,
    *,
    target_root: Path | None = None,
) -> list[dict]:
    status: list[dict] = []
    known_roots = legacy_global_roots(home)
    for target in adapter_targets(repo_root, home, platform_ids=platform_ids, target_root=target_root):
        repo_path = target["repo_path"]
        path_state = adapter_path_state(repo_path, global_root, known_global_roots=known_roots)
        status.append(
            {
                "platform": target["platform"],
                "repo_path": str(repo_path),
                **path_state,
                "verify_rules": target["verify_rules"],
            }
        )
    return status

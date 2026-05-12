from __future__ import annotations

from pathlib import Path
import shutil

from .adapters import adapter_path_state, validate_platform_selectors
from .lockfile import load_json
from .manifests import load_pack_config
from .paths import expand_user_path, repo_path
from .registry import load_registry, package_has_other_refs, remove_target


def _require_under_global_root(path: Path, global_root: Path) -> None:
    resolved_path = path.resolve(strict=False)
    resolved_root = global_root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to rollback managed package outside global root: {path}") from exc


def _require_adapter_under_target_root(path: Path, target_root: Path) -> None:
    resolved_parent = path.parent.resolve(strict=False)
    resolved_root = target_root.resolve(strict=False)
    try:
        resolved_parent.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to rollback adapter outside target root: {path}") from exc


def rollback(
    repo_root: Path,
    home: Path,
    platform_ids: list[str] | None = None,
    *,
    target_root: Path | None = None,
) -> dict:
    validate_platform_selectors(repo_root, platform_ids)
    if platform_ids:
        raise ValueError("platform-scoped rollback is not supported in v3; run full rollback to remove shared managed state")

    attachment_root = target_root or repo_root
    pack = load_pack_config(repo_root)
    lock_path = repo_path(attachment_root, pack.lockfile, "repo.lockfile")
    lock = load_json(lock_path)
    removed: list[str] = []

    registry = expand_user_path(pack.global_registry, home)
    registry_payload = load_registry(registry)

    global_root = expand_user_path(pack.global_root, home)
    for skill_path_str in [*lock.get("installed_skills", []), *lock.get("installed_workflows", [])]:
        skill_path = Path(skill_path_str)
        _require_under_global_root(skill_path, global_root)
        if package_has_other_refs(registry_payload, skill_path.name, target_root=attachment_root):
            continue
        if skill_path.exists() and (skill_path / ".localsetup-managed").exists():
            shutil.rmtree(skill_path)
            removed.append(str(skill_path))

    if registry.exists():
        before = registry.exists()
        remove_target(registry, target_root=attachment_root)
        if before and not registry.exists():
            removed.append(str(registry))

    for adapter_path in lock.get("adapter_state", []):
        p = Path(str(adapter_path))
        if not p.is_absolute():
            p = attachment_root / p
        _require_adapter_under_target_root(p, attachment_root)
        if p.exists() or p.is_symlink():
            state = adapter_path_state(p, global_root)
            if p.is_dir() and not p.is_symlink():
                if (p / ".localsetup-portable").exists():
                    shutil.rmtree(p)
                    removed.append(str(p))
                continue
            if not state["points_to_global"]:
                continue
            p.unlink()
            removed.append(str(p))

    if global_root.exists() and not any(global_root.iterdir()):
        global_root.rmdir()
        removed.append(str(global_root))

    if lock_path.exists():
        lock_path.unlink()
        removed.append(str(lock_path))

    return {"removed": removed}

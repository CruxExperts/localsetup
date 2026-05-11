from __future__ import annotations

from pathlib import Path
import shutil

from .adapters import adapter_targets, validate_platform_selectors
from .lockfile import load_json
from .manifests import load_pack_config
from .paths import expand_user_path, repo_path


def _require_under_global_root(path: Path, global_root: Path) -> None:
    resolved_path = path.resolve(strict=False)
    resolved_root = global_root.resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise RuntimeError(f"refusing to rollback managed package outside global root: {path}") from exc


def rollback(repo_root: Path, home: Path, platform_ids: list[str] | None = None) -> dict:
    validate_platform_selectors(repo_root, platform_ids)
    if platform_ids:
        raise ValueError("platform-scoped rollback is not supported in v3; run full rollback to remove shared managed state")

    pack = load_pack_config(repo_root)
    lock_path = repo_path(repo_root, pack.lockfile, "repo.lockfile")
    lock = load_json(lock_path)
    removed: list[str] = []

    if lock_path.exists():
        lock_path.unlink()
        removed.append(str(lock_path))

    registry = expand_user_path(pack.global_registry, home)
    if registry.exists():
        registry.unlink()
        removed.append(str(registry))

    global_root = expand_user_path(pack.global_root, home)
    for skill_path_str in [*lock.get("installed_skills", []), *lock.get("installed_workflows", [])]:
        skill_path = Path(skill_path_str)
        _require_under_global_root(skill_path, global_root)
        if skill_path.exists() and (skill_path / ".localsetup-managed").exists():
            shutil.rmtree(skill_path)
            removed.append(str(skill_path))

    selected_platforms = platform_ids or lock.get("platforms")
    for target in adapter_targets(repo_root, home, platform_ids=selected_platforms):
        p = target["repo_path"]
        if p.exists() or p.is_symlink():
            if p.is_dir() and not p.is_symlink():
                if (p / ".localsetup-portable").exists():
                    shutil.rmtree(p)
                    removed.append(str(p))
                continue
            p.unlink()
            removed.append(str(p))

    if global_root.exists() and not any(global_root.iterdir()):
        global_root.rmdir()
        removed.append(str(global_root))

    return {"removed": removed}

from __future__ import annotations

from pathlib import Path
import shutil

from .adapters import remove_managed_adapter_entries, legacy_global_roots, validate_platform_selectors
from .lockfile import load_json
from .manifests import load_pack_config
from .package_cleanup import is_package_backup_artifact
from .paths import expand_user_path, legacy_target_lockfile_path, repo_path, target_lockfile_path
from .provenance import is_managed_package
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


def _remove_unreferenced_managed_packages(global_root: Path, registry_payload: dict) -> list[str]:
    if not global_root.exists():
        return []
    referenced = {
        name
        for name, package in registry_payload.get("packages", {}).items()
        if isinstance(package, dict) and package.get("refs")
    }
    removed: list[str] = []
    for path in sorted(global_root.iterdir(), key=lambda item: item.name):
        if path.name.startswith(".localsetup-") or is_package_backup_artifact(path) or path.name in referenced:
            continue
        if path.exists() and is_managed_package(path):
            shutil.rmtree(path)
            removed.append(str(path))
    return removed


def _remove_managed_shared_runtime_helper(repo_root: Path, global_root: Path, registry_payload: dict) -> list[str]:
    if registry_payload.get("targets") or registry_payload.get("packages") or registry_payload.get("personal_owners"):
        return []
    source = repo_root / "ls" / "lib" / "deps.py"
    target = global_root.parent / "lib" / "deps.py"
    if not source.is_file() or not target.is_file() or target.is_symlink():
        return []
    if source.read_bytes() != target.read_bytes():
        return []
    target.unlink()
    removed = [str(target)]
    if target.parent.exists() and not any(target.parent.iterdir()):
        target.parent.rmdir()
        removed.append(str(target.parent))
    return removed


def rollback(
    repo_root: Path,
    home: Path,
    platform_ids: list[str] | None = None,
    *,
    target_root: Path | None = None,
) -> dict:
    validate_platform_selectors(repo_root, platform_ids)
    if platform_ids:
        raise ValueError("platform-scoped rollback is not supported in the current framework; run full rollback to remove shared managed state")

    attachment_root = target_root or repo_root
    pack = load_pack_config(repo_root)
    lock_path = repo_path(attachment_root, pack.lockfile, "repo.lockfile")
    if lock_path.name != "lock.json" or lock_path.parent.name != ".localsetup":
        lock_path = target_lockfile_path(attachment_root)
    lock = load_json(lock_path)
    legacy_lock = legacy_target_lockfile_path(attachment_root)
    if not lock and legacy_lock.exists():
        lock = load_json(legacy_lock)
    removed: list[str] = []

    registry = expand_user_path(pack.global_registry, home)
    registry_payload = load_registry(registry)
    from .personal_registry import refuse_personal_overlap
    refuse_personal_overlap(registry_payload, [str(Path(p) if Path(p).is_absolute() else attachment_root / p) for p in lock.get("adapter_state", [])])

    global_root = expand_user_path(pack.global_root, home)
    for skill_path_str in [*lock.get("installed_skills", []), *lock.get("installed_workflows", [])]:
        skill_path = Path(skill_path_str)
        _require_under_global_root(skill_path, global_root)
        if package_has_other_refs(registry_payload, skill_path.name, target_root=attachment_root):
            continue
        if skill_path.exists() and is_managed_package(skill_path):
            shutil.rmtree(skill_path)
            removed.append(str(skill_path))

    if registry.exists():
        before = registry.exists()
        registry_payload = remove_target(registry, target_root=attachment_root)
        if before and not registry.exists():
            removed.append(str(registry))
        removed.extend(_remove_unreferenced_managed_packages(global_root, registry_payload))

    for adapter_path in lock.get("adapter_state", []):
        p = Path(str(adapter_path))
        if not p.is_absolute():
            p = attachment_root / p
        _require_adapter_under_target_root(p, attachment_root)
        removed.extend(remove_managed_adapter_entries(p, global_root, known_global_roots=legacy_global_roots(home)))

    if global_root.exists() and not any(global_root.iterdir()):
        global_root.rmdir()
        removed.append(str(global_root))

    removed.extend(_remove_managed_shared_runtime_helper(repo_root, global_root, registry_payload))

    if lock_path.exists():
        lock_path.unlink()
        removed.append(str(lock_path))
    if legacy_lock.exists():
        legacy_lock.unlink()
        removed.append(str(legacy_lock))

    return {"removed": removed}

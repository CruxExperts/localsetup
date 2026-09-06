from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile

from .installation_ownership import repository_owners

from .adapters import adapter_targets, legacy_global_roots, remove_managed_adapter_entries
from .lockfile import load_json, save_json, save_text
from .locking import package_root_lock
from .manifests import load_pack_config
from .paths import expand_user_path, target_lockfile_path
from .registry import load_registry


@dataclass
class _NodeSnapshot:
    path: Path
    existed: bool
    backup: Path | None


@dataclass
class _FileSnapshot:
    path: Path
    existed: bool
    data: bytes | None


def _snapshot_node(path: Path, backup_root: Path, index: int) -> _NodeSnapshot:
    existed = path.exists() or path.is_symlink()
    if not existed:
        return _NodeSnapshot(path=path, existed=False, backup=None)
    backup = backup_root / str(index)
    if path.is_symlink():
        backup.symlink_to(path.readlink())
    elif path.is_dir():
        shutil.copytree(path, backup, symlinks=True)
    elif path.is_file():
        shutil.copy2(path, backup)
    else:
        raise RuntimeError(f"cannot snapshot unsupported adapter node: {path}")
    if not (backup.exists() or backup.is_symlink()):
        raise RuntimeError(f"adapter snapshot was not created: {path}")
    return _NodeSnapshot(path=path, existed=True, backup=backup)


def _remove_node(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _restore_node(snapshot: _NodeSnapshot) -> None:
    _remove_node(snapshot.path)
    if not snapshot.existed:
        return
    if snapshot.backup is None or not (snapshot.backup.exists() or snapshot.backup.is_symlink()):
        raise RuntimeError(f"required detach snapshot is missing: {snapshot.path}")
    snapshot.path.parent.mkdir(parents=True, exist_ok=True)
    if snapshot.backup.is_symlink():
        snapshot.path.symlink_to(snapshot.backup.readlink())
    elif snapshot.backup.is_dir():
        shutil.copytree(snapshot.backup, snapshot.path, symlinks=True)
    else:
        shutil.copy2(snapshot.backup, snapshot.path)


def _snapshot_file(path: Path) -> _FileSnapshot:
    if path.is_symlink():
        raise RuntimeError(f"transaction receipt must not be a symlink: {path}")
    return _FileSnapshot(path=path, existed=path.is_file(), data=path.read_bytes() if path.is_file() else None)


def _restore_file(snapshot: _FileSnapshot) -> None:
    if snapshot.existed:
        if snapshot.data is None:
            raise RuntimeError(f"required receipt snapshot is missing: {snapshot.path}")
        save_text(snapshot.path, snapshot.data.decode("utf-8"))
    elif snapshot.path.exists() or snapshot.path.is_symlink():
        _remove_node(snapshot.path)


def _updated_registry(registry: dict, *, target_root: Path, adapter_receipts: list[dict], remaining: bool) -> dict:
    target_id = str(target_root.resolve(strict=False))
    updated = {
        **registry,
        "targets": {key: dict(value) for key, value in registry.get("targets", {}).items()},
        "packages": {key: dict(value) for key, value in registry.get("packages", {}).items()},
    }
    if remaining:
        receipt = updated["targets"].get(target_id)
        if isinstance(receipt, dict):
            receipt["adapters"] = adapter_receipts
        return updated
    updated["targets"].pop(target_id, None)
    for package_name, package in list(updated["packages"].items()):
        refs = [str(ref) for ref in package.get("refs", []) if str(ref) != target_id]
        if refs:
            package["refs"] = refs
        else:
            updated["packages"].pop(package_name, None)
    return updated


def _detach_platforms_locked(repo_root: Path, home: Path, target_root: Path, platform_ids: list[str]) -> dict:
    requested = set(platform_ids)
    pack = load_pack_config(repo_root)
    global_root = expand_user_path(pack.global_root, home)
    lock_path = target_lockfile_path(target_root)
    registry_path = expand_user_path(pack.global_registry, home)
    lock = load_json(lock_path)
    registry = load_registry(registry_path)
    recorded_by_path = {
        str(item.get("path")): item
        for item in lock.get("adapter_targets", [])
        if isinstance(item, dict) and item.get("path")
    }
    physical_targets = adapter_targets(repo_root, home, platform_ids=platform_ids, target_root=target_root)
    remove_targets: list[dict] = []
    for target in physical_targets:
        recorded = recorded_by_path.get(str(target["repo_path"]), {})
        owners = set(
            recorded.get("platforms")
            or ([recorded.get("platform")] if recorded.get("platform") else target["platforms"])
        )
        if not owners - requested:
            remove_targets.append(target)

    from .personal_registry import refuse_personal_overlap
    refuse_personal_overlap(registry, [str(target["repo_path"]) for target in remove_targets])

    updated_lock = dict(lock)
    updated_lock["platforms"] = sorted(set(lock.get("platforms", [])) - requested)
    updated_targets: list = []
    removed_paths = {str(target["repo_path"]) for target in remove_targets}
    for item in lock.get("adapter_targets", []):
        if not isinstance(item, dict):
            updated_targets.append(item)
            continue
        owners = set(item.get("platforms") or ([item.get("platform")] if item.get("platform") else []))
        remaining_owners = sorted(owners - requested)
        if not remaining_owners:
            continue
        updated = dict(item)
        updated["platforms"] = remaining_owners
        updated["owners"] = repository_owners(target_root, remaining_owners)
        updated["platform"] = remaining_owners[0]
        updated_targets.append(updated)
    updated_lock["adapter_targets"] = updated_targets
    updated_lock["adapter_state"] = [
        path for path in lock.get("adapter_state", []) if str(path) not in removed_paths
    ]
    remaining = bool(updated_lock["platforms"])
    updated_registry = _updated_registry(
        registry,
        target_root=target_root,
        adapter_receipts=updated_targets,
        remaining=remaining,
    )

    removed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="localsetup-detach-") as temporary:
        backup_root = Path(temporary)
        node_snapshots = [
            _snapshot_node(target["repo_path"], backup_root, index)
            for index, target in enumerate(remove_targets)
        ]
        lock_snapshot = _snapshot_file(lock_path)
        registry_snapshot = _snapshot_file(registry_path)
        try:
            for target in remove_targets:
                removed.extend(
                    remove_managed_adapter_entries(
                        target["repo_path"],
                        global_root,
                        known_global_roots=legacy_global_roots(home),
                        recorded_packages=recorded_by_path.get(str(target["repo_path"]), {}).get("packages"),
                    )
                )
            if lock:
                save_json(lock_path, updated_lock)
            if updated_registry.get("targets") or updated_registry.get("packages") or updated_registry.get("personal_owners"):
                save_json(registry_path, updated_registry)
            elif registry_path.exists():
                _unlink_registry(registry_path)
        except Exception as exc:
            rollback_errors: list[str] = []
            for restore in (
                lambda: _restore_file(registry_snapshot),
                lambda: _restore_file(lock_snapshot),
                *[lambda snapshot=snapshot: _restore_node(snapshot) for snapshot in reversed(node_snapshots)],
            ):
                try:
                    restore()
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if rollback_errors:
                exc.add_note("detach rollback errors: " + "; ".join(rollback_errors))
            raise
    return {"removed": removed, "packages_preserved": True}


def _unlink_registry(registry_path: Path) -> None:
    registry_path.unlink()


def detach_platforms(repo_root: Path, home: Path, target_root: Path, platform_ids: list[str]) -> dict:
    with package_root_lock(home / ".local" / "share" / "localsetup"):
        return _detach_platforms_locked(repo_root, home, target_root, platform_ids)

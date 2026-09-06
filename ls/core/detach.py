from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
import os
import uuid

from .installation_ownership import repository_owners

from .adapters import legacy_global_roots, remove_managed_adapter_entries
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


def _detach_platforms_locked(repo_root: Path, home: Path, target_root: Path, platform_ids: list[str], *, preserve_neighbors: bool = False) -> dict:
    requested = set(platform_ids)
    pack = load_pack_config(repo_root)
    global_root = expand_user_path(pack.global_root, home)
    lock_path = target_lockfile_path(target_root)
    registry_path = expand_user_path(pack.global_registry, home)
    lock = load_json(lock_path)
    registry = load_registry(registry_path)
    from .detach_records import recorded_detach_rows
    rows = recorded_detach_rows(lock, target_root)
    if not any(owners & requested for _, _, owners in rows):
        return {"removed": [], "packages_preserved": True, "warnings": []}
    recorded_by_path = {str(path): row for path, row, _ in rows}
    remove_targets = [{"repo_path": path, "platforms": sorted(owners)}
                      for path, _, owners in rows if owners & requested and not owners - requested]

    from .shared_detach import shared_detach_actions
    from .repository_overlap import write_overlap
    from .adapter_markers import adapter_marker_packages
    from .apply_journal import journal_path, record_file_state, write_journal, restore_failed_mutations, cleanup_backups
    shared = shared_detach_actions(repo_root, home, target_root, remove_targets, recorded_by_path,
                                   global_root, lock.get("attach_mode", "symlink"))
    journaled = bool(shared) or preserve_neighbors
    shared_journal = {"version": 1, "status": "started", "operation": "detach", "touched": []}
    shared_journal_path = journal_path(target_root, "detach-" + uuid.uuid4().hex)

    updated_lock = dict(lock)
    updated_lock["platforms"] = sorted(set(lock.get("platforms", [])) - requested)
    updated_targets: list = []
    removed_paths = {str(target["repo_path"]) for target in remove_targets}
    for _, item, owners in rows:
        if not owners & requested:
            updated_targets.append(item)
            continue
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
        path for path in lock.get("adapter_state", [])
        if str(Path(path) if Path(path).is_absolute() else target_root / path) not in removed_paths
    ]
    personal_targets = lock.get("personal_adapter_targets", [])
    personal_clients = {owner["client"] for item in personal_targets for owner in item.get("owners", [])}
    updated_lock["platforms"] = sorted(set(updated_lock["platforms"]) | personal_clients)
    if personal_targets and not updated_targets:
        updated_lock["skill_scope"] = "personal"
    remaining = bool(updated_lock["platforms"])
    updated_registry = _updated_registry(
        registry,
        target_root=target_root,
        adapter_receipts=[*updated_targets, *personal_targets],
        remaining=remaining,
    )

    removed: list[str] = []
    cleanup_warnings: list[str] = []
    with tempfile.TemporaryDirectory(prefix="localsetup-detach-") as temporary:
        backup_root = Path(temporary)
        node_snapshots = [
            _snapshot_node(target["repo_path"], backup_root, index)
            for index, target in enumerate(remove_targets) if str(target["repo_path"]) not in shared and not preserve_neighbors
        ]
        lock_snapshot = _snapshot_file(lock_path)
        registry_snapshot = _snapshot_file(registry_path)
        try:
            if journaled:
                record_file_state(shared_journal, shared_journal_path, lock_path, os.replace)
                record_file_state(shared_journal, shared_journal_path, registry_path, os.replace)
            for target in remove_targets:
                if str(target["repo_path"]) in shared:
                    action, expected = shared[str(target["repo_path"])]
                    old = adapter_marker_packages(action.path) or set()
                    write_overlap(repo_root, home, target_root, action, shared_journal, shared_journal_path)
                    removed.extend(str(action.path / name) for name in sorted(old - set(expected)))
                    continue
                if preserve_neighbors:
                    from .shared_rollback import _snapshot_adapter
                    _snapshot_adapter(target["repo_path"], global_root, shared_journal, shared_journal_path,
                                      recorded_by_path[str(target["repo_path"])].get("packages"))
                removed.extend(
                    remove_managed_adapter_entries(
                        target["repo_path"],
                        global_root,
                        known_global_roots=legacy_global_roots(home),
                        recorded_packages=recorded_by_path.get(str(target["repo_path"]), {}).get("packages"),
                        preserve_directory=preserve_neighbors,
                    )
                )
            if lock:
                save_json(lock_path, updated_lock)
            if updated_registry.get("targets") or updated_registry.get("packages") or updated_registry.get("personal_owners"):
                save_json(registry_path, updated_registry)
            elif registry_path.exists():
                _unlink_registry(registry_path)
            if journaled:
                shared_journal["status"] = "committed"
                write_journal(shared_journal_path, shared_journal)
        except Exception as exc:
            rollback_errors: list[str] = []
            for restore in (
                *([lambda: restore_failed_mutations(shared_journal, os.replace)] if journaled else []),
                lambda: _restore_file(registry_snapshot),
                lambda: _restore_file(lock_snapshot),
                *[lambda snapshot=snapshot: _restore_node(snapshot) for snapshot in reversed(node_snapshots)],
            ):
                try:
                    restore()
                except Exception as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if journaled:
                shared_journal["status"] = "failed"
                shared_journal["rollback_errors"] = rollback_errors
                write_journal(shared_journal_path, shared_journal)
            if rollback_errors:
                exc.add_note("detach rollback errors: " + "; ".join(rollback_errors))
            raise
        if journaled:
            try:cleanup_backups(shared_journal)
            except OSError as exc:
                cleanup_warnings.append(f"detach committed; backup cleanup failed: {exc}")
    return {"removed": removed, "packages_preserved": True, "warnings": cleanup_warnings,
            **({"journal": str(shared_journal_path)} if journaled else {})}


def _unlink_registry(registry_path: Path) -> None:
    registry_path.unlink()


def detach_platforms(repo_root: Path, home: Path, target_root: Path, platform_ids: list[str]) -> dict:
    with package_root_lock(home / ".local" / "share" / "localsetup"):
        return _detach_platforms_locked(repo_root, home, target_root, platform_ids)

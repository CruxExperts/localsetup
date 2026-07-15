from __future__ import annotations

from pathlib import Path
import shutil
import time
import uuid

from .lockfile import save_json


class RollbackError(RuntimeError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("rollback encountered errors: " + "; ".join(errors))


def journal_root(attachment_root: Path) -> Path:
    return attachment_root / ".localsetup" / "install-journal"


def journal_path(attachment_root: Path, txid: str) -> Path:
    return journal_root(attachment_root) / f"{int(time.time() * 1000)}-{txid}.json"


def staging_root(global_root: Path, txid: str) -> Path:
    return global_root / ".localsetup-staging" / txid


def remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def write_journal(path: Path, payload: dict) -> None:
    save_json(path, payload)


def cleanup_staging(journal: dict) -> None:
    staging_roots = {
        Path(item["staging_root"])
        for item in journal.get("touched", [])
        if isinstance(item, dict) and item.get("kind") == "staging_root" and item.get("staging_root")
    }
    for root in staging_roots:
        if root.exists() or root.is_symlink():
            remove_path(root)


def cleanup_backups(journal: dict) -> None:
    for item in journal.get("touched", []):
        if not isinstance(item, dict) or item.get("kind") not in {"managed_package", "adapter", "file_state"}:
            continue
        backup = item.get("backup")
        if backup:
            backup_path = Path(backup)
            if backup_path.exists() or backup_path.is_symlink():
                remove_path(backup_path)


def restore_failed_mutations(journal: dict, replace_func) -> None:
    restorable = [
        item
        for item in reversed(journal.get("touched", []))
        if isinstance(item, dict) and item.get("kind") in {"managed_package", "adapter", "file_state", "legacy_lockfile"}
    ]
    errors: list[str] = []
    for item in restorable:
        path = Path(str(item["path"]))
        backup = Path(str(item["backup"])) if item.get("backup") else None
        existed = bool(item.get("existed"))
        backup_exists = bool(backup and (backup.exists() or backup.is_symlink()))
        if existed and not backup_exists:
            errors.append(f"required backup is missing for {path}: {backup}")
            continue
        try:
            if path.exists() or path.is_symlink():
                remove_path(path)
            if existed and backup:
                replace_func(backup, path)
            elif backup_exists and backup:
                remove_path(backup)
        except Exception as exc:
            errors.append(f"failed to restore {path}: {exc}")
    if errors:
        raise RollbackError(errors)


def record_file_state(journal: dict, journal_path: Path, path: Path, replace_func) -> None:
    if any(
        item.get("kind") == "file_state" and item.get("path") == str(path)
        for item in journal.get("touched", [])
        if isinstance(item, dict)
    ):
        return
    backup = path.with_name(f".{path.name}.localsetup-backup-{uuid.uuid4().hex}")
    existed = path.exists() or path.is_symlink()
    if existed:
        if path.is_symlink():
            backup.symlink_to(path.readlink())
        else:
            shutil.copy2(path, backup)
        if not (backup.exists() or backup.is_symlink()):
            raise RuntimeError(f"file-state backup was not created: {backup}")
    journal.setdefault("touched", []).append(
        {"kind": "file_state", "path": str(path), "backup": str(backup), "existed": existed}
    )
    write_journal(journal_path, journal)


def prepare_legacy_lockfile_backup(legacy_lockfile: Path, attachment_root: Path, txid: str) -> str | None:
    if not (legacy_lockfile.exists() or legacy_lockfile.is_symlink()):
        return None
    backup = attachment_root / ".localsetup" / "backups" / f"legacy-lock-{txid}" / legacy_lockfile.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    if legacy_lockfile.is_symlink():
        backup.symlink_to(legacy_lockfile.readlink())
        if not backup.is_symlink() or backup.readlink() != legacy_lockfile.readlink():
            raise RuntimeError(f"legacy lock symlink backup verification failed: {backup}")
    else:
        shutil.copy2(legacy_lockfile, backup)
        if not backup.is_file() or backup.read_bytes() != legacy_lockfile.read_bytes():
            raise RuntimeError(f"legacy lock backup verification failed: {backup}")
    return str(backup)


def remove_legacy_lockfile(legacy_lockfile: Path) -> None:
    legacy_lockfile.unlink()


def archive_legacy_lockfile(legacy_lockfile: Path, attachment_root: Path, txid: str) -> str | None:
    backup = prepare_legacy_lockfile_backup(legacy_lockfile, attachment_root, txid)
    if backup is not None:
        remove_legacy_lockfile(legacy_lockfile)
    return backup

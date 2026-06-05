from __future__ import annotations

from pathlib import Path
import shutil
import time
import uuid

from .lockfile import save_json


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
    for item in reversed(journal.get("touched", [])):
        if not isinstance(item, dict) or item.get("kind") not in {"managed_package", "adapter", "file_state", "legacy_lockfile"}:
            continue
        path = Path(str(item["path"]))
        backup = Path(str(item["backup"])) if item.get("backup") else None
        existed = bool(item.get("existed"))
        if path.exists() or path.is_symlink():
            remove_path(path)
        if existed and backup and (backup.exists() or backup.is_symlink()):
            replace_func(backup, path)
        elif backup and (backup.exists() or backup.is_symlink()):
            remove_path(backup)


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
            replace_func(path, backup)
            replace_func(backup, path)
        else:
            shutil.copy2(path, backup)
    journal.setdefault("touched", []).append(
        {"kind": "file_state", "path": str(path), "backup": str(backup), "existed": existed}
    )
    write_journal(journal_path, journal)


def archive_legacy_lockfile(legacy_lockfile: Path, attachment_root: Path, txid: str) -> str | None:
    if not (legacy_lockfile.exists() or legacy_lockfile.is_symlink()):
        return None
    backup = attachment_root / ".localsetup" / "backups" / f"legacy-lock-{txid}" / legacy_lockfile.name
    backup.parent.mkdir(parents=True, exist_ok=True)
    if legacy_lockfile.is_symlink():
        backup.write_text(f"symlink -> {legacy_lockfile.readlink()}\n", encoding="utf-8")
        legacy_lockfile.unlink()
    else:
        shutil.copy2(legacy_lockfile, backup)
        legacy_lockfile.unlink()
    return str(backup)

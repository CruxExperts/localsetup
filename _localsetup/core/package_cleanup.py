from __future__ import annotations

from pathlib import Path


def is_package_backup_artifact(path: Path) -> bool:
    name = path.name
    return name.startswith(".") and ".localsetup-backup-" in name

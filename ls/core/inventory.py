from __future__ import annotations

from pathlib import Path
from typing import Any

from .adapters import adapter_status, legacy_global_roots
from .lockfile import load_json
from .personal_inventory import personal_inventory
from .manifests import load_pack_config
from .paths import expand_user_path, target_lockfile_path
from .provenance import has_legacy_marker, is_managed_package


def _package_rows(root: Path, *, scope: str) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.iterdir() if item.is_dir()):
        if path.name.startswith("."):
            continue
        rows.append(
            {
                "name": path.name,
                "path": str(path),
                "scope": scope,
                "managed": is_managed_package(path),
                "legacy_marker": has_legacy_marker(path),
            }
        )
    return rows


def install_inventory(
    repo_root: Path,
    *,
    home: Path,
    target_root: Path | None = None,
    platform_ids: list[str] | None = None,
) -> dict[str, Any]:
    pack = load_pack_config(repo_root)
    attachment_root = target_root or repo_root
    global_root = expand_user_path(pack.global_root, home)
    legacy_roots = legacy_global_roots(home)
    lock_path = target_lockfile_path(attachment_root)
    lock = load_json(lock_path)
    adapters = [] if lock.get("skill_scope") == "personal" else adapter_status(repo_root, home, global_root, platform_ids=platform_ids, target_root=attachment_root)
    return {
        "target_root": str(attachment_root),
        "lockfile": {
            "path": str(lock_path),
            "exists": bool(lock),
            "skills": lock.get("skills", []),
            "workflows": lock.get("workflows", []),
            "platforms": lock.get("platforms", []),
            "skill_scope": lock.get("skill_scope", "repo"),
            "adapter_packages": lock.get("adapter_packages", []),
            "global_baseline_packages": lock.get("global_baseline_packages", []),
            "global_baseline_selectors": lock.get("global_baseline_selectors", {}),
            "repo_packages": lock.get("repo_packages", lock.get("adapter_packages", [])),
            "repo_selectors": lock.get("repo_selectors", lock.get("selectors", {})),
        },
        "package_roots": {
            "current": str(global_root),
            "current_exists": global_root.exists(),
            "legacy": [str(path) for path in legacy_roots],
            "legacy_existing": [str(path) for path in legacy_roots if path.exists()],
        },
        "packages": [
            *_package_rows(global_root, scope="current-global"),
            *[row for root in legacy_roots for row in _package_rows(root, scope="legacy-global")],
        ],
        "adapters": adapters,
        "personal": personal_inventory(repo_root, home, platform_ids),
    }

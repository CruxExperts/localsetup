from __future__ import annotations

from pathlib import Path

from .adapters import adapter_status
from .lockfile import load_json
from .manifests import load_pack_config
from .paths import expand_user_path, repo_path


def verify_install(repo_root: Path, home: Path, platform_ids: list[str] | None = None) -> dict:
    pack = load_pack_config(repo_root)
    lock = load_json(repo_path(repo_root, pack.lockfile, "repo.lockfile"))
    global_root = expand_user_path(pack.global_root, home)

    issues: list[str] = []
    if not lock:
        issues.append("missing lockfile")
    attach_mode = lock.get("attach_mode", "symlink") if isinstance(lock, dict) else "symlink"

    if not global_root.is_dir():
        issues.append(f"missing global skill library: {global_root}")

    aliases = lock.get("aliases", {}) if isinstance(lock, dict) else {}
    for skill_name in sorted(set(aliases.values())):
        skill_path = global_root / skill_name
        if not skill_path.is_dir():
            issues.append(f"missing managed skill: {skill_path}")
        elif not (skill_path / ".localsetup-managed").exists():
            issues.append(f"managed marker missing: {skill_path}")

    for adapter in adapter_status(repo_root, home, global_root, platform_ids=platform_ids):
        if not adapter["exists"]:
            issues.append(f"missing adapter path: {adapter['repo_path']}")
        elif attach_mode == "portable" and not adapter["is_portable_copy"]:
            issues.append(f"adapter is not a managed portable copy: {adapter['repo_path']}")
        elif attach_mode != "portable" and not adapter["points_to_global"]:
            issues.append(f"adapter does not point at global library: {adapter['repo_path']}")

    registry_path = expand_user_path(pack.global_registry, home)
    if not registry_path.exists():
        issues.append(f"missing global registry: {registry_path}")

    return {
        "ok": not issues,
        "issues": issues,
        "adapters": adapter_status(repo_root, home, global_root, platform_ids=platform_ids),
    }

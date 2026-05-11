from __future__ import annotations

from pathlib import Path

from .adapters import adapter_path_state, adapter_status
from .lockfile import load_json
from .manifests import load_pack_config
from .paths import expand_user_path, repo_path


def _recorded_adapter_status(lock: dict, global_root: Path) -> list[dict]:
    recorded = lock.get("adapter_targets") if isinstance(lock, dict) else None
    if not recorded:
        recorded = [
            {"platform": None, "path": path, "mode": lock.get("attach_mode", "symlink"), "global_root": str(global_root)}
            for path in lock.get("adapter_state", [])
        ]
    statuses: list[dict] = []
    for item in recorded:
        path = Path(str(item["path"]))
        expected_global = Path(str(item.get("global_root") or global_root))
        statuses.append(
            {
                "platform": item.get("platform"),
                "repo_path": str(path),
                "expected_mode": item.get("mode", lock.get("attach_mode", "symlink")),
                **adapter_path_state(path, expected_global),
                "verify_rules": [],
            }
        )
    return statuses


def verify_install(
    repo_root: Path,
    home: Path,
    platform_ids: list[str] | None = None,
    *,
    target_root: Path | None = None,
) -> dict:
    pack = load_pack_config(repo_root)
    attachment_root = target_root or repo_root
    lock = load_json(repo_path(attachment_root, pack.lockfile, "repo.lockfile"))
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

    workflows = lock.get("workflows", []) if isinstance(lock, dict) else []
    for workflow_name in sorted(set(workflows)):
        workflow_path = global_root / workflow_name
        if not workflow_path.is_dir():
            issues.append(f"missing managed workflow: {workflow_path}")
        elif not (workflow_path / ".localsetup-managed").exists():
            issues.append(f"managed marker missing: {workflow_path}")

    adapters = (
        adapter_status(repo_root, home, global_root, platform_ids=platform_ids, target_root=attachment_root)
        if platform_ids is not None
        else _recorded_adapter_status(lock, global_root)
    )
    for adapter in adapters:
        expected_mode = adapter.get("expected_mode", attach_mode)
        if not adapter["exists"]:
            issues.append(f"missing adapter path: {adapter['repo_path']}")
        elif expected_mode == "portable" and not adapter["is_portable_copy"]:
            issues.append(f"adapter is not a managed portable copy: {adapter['repo_path']}")
        elif expected_mode != "portable" and not adapter["points_to_global"]:
            issues.append(f"adapter does not point at global library: {adapter['repo_path']}")

    registry_path = expand_user_path(pack.global_registry, home)
    if not registry_path.exists():
        issues.append(f"missing global registry: {registry_path}")

    return {
        "ok": not issues,
        "issues": issues,
        "adapters": adapters,
    }

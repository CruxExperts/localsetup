from __future__ import annotations

from pathlib import Path

from .adapters import adapter_path_state, adapter_status
from .lockfile import load_json
from .manifests import load_pack_config, load_platforms
from .paths import expand_user_path, repo_path
from .workflows import validate_workflow_catalog


SUPPORTED_LEVELS = {"filesystem", "host", "smoke"}


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
    level: str = "filesystem",
) -> dict:
    if level not in SUPPORTED_LEVELS:
        raise ValueError(f"unsupported verify level: {level}")
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
    platform_rules = {platform.platform_id: platform.verify_rules for platform in load_platforms(repo_root)}
    rule_results: list[dict] = []
    for adapter in adapters:
        expected_mode = adapter.get("expected_mode", attach_mode)
        rules = platform_rules.get(str(adapter.get("platform")), adapter.get("verify_rules", []))
        if level != "filesystem":
            rule_results.append({"level": level, "status": "not_run", "reason": f"{level} probes are not implemented yet", "platform": adapter.get("platform")})
        if "adapter_path_exists" in rules or rules:
            ok = bool(adapter["exists"])
            rule_results.append({"rule": "adapter_path_exists", "platform": adapter.get("platform"), "ok": ok, "path": adapter["repo_path"]})
            if not ok:
                issues.append(f"verify rule adapter_path_exists failed: {adapter['repo_path']}")
        if "adapter_points_to_managed_root" in rules or expected_mode != "portable":
            ok = bool(adapter["points_to_global"]) if expected_mode != "portable" else True
            rule_results.append({"rule": "adapter_points_to_managed_root", "platform": adapter.get("platform"), "ok": ok, "path": adapter["repo_path"]})
            if not ok:
                issues.append(f"verify rule adapter_points_to_managed_root failed: {adapter['repo_path']}")
        if "portable_marker_valid" in rules or expected_mode == "portable":
            ok = bool(adapter["is_portable_copy"]) if expected_mode == "portable" else True
            rule_results.append({"rule": "portable_marker_valid", "platform": adapter.get("platform"), "ok": ok, "path": adapter["repo_path"]})
            if not ok:
                issues.append(f"verify rule portable_marker_valid failed: {adapter['repo_path']}")
        if not adapter["exists"]:
            issues.append(f"missing adapter path: {adapter['repo_path']}")
        elif expected_mode == "portable" and not adapter["is_portable_copy"]:
            issues.append(f"adapter is not a managed portable copy: {adapter['repo_path']}")
        elif expected_mode != "portable" and not adapter["points_to_global"]:
            issues.append(f"adapter does not point at global library: {adapter['repo_path']}")
        if "namespace_ls" in rules:
            ok = all(Path(path).name.startswith("ls-") for path in [*lock.get("installed_skills", []), *lock.get("installed_workflows", [])])
            rule_results.append({"rule": "namespace_ls", "platform": adapter.get("platform"), "ok": ok})
            if not ok:
                issues.append(f"verify rule namespace_ls failed: {adapter.get('platform')}")
        if "skills_visible" in rules or "skills_visible_filesystem" in rules:
            visible = [path for path in lock.get("installed_skills", []) if (Path(path) / "SKILL.md").is_file()]
            ok = len(visible) == len(lock.get("installed_skills", []))
            rule_results.append({"rule": "skills_visible_filesystem", "platform": adapter.get("platform"), "ok": ok, "visible_count": len(visible)})
            if not ok:
                issues.append(f"verify rule skills_visible_filesystem failed: {adapter.get('platform')}")

    workflow_issues = validate_workflow_catalog(repo_root, validate_references=False) if lock.get("workflows") else []
    rule_results.append({"rule": "workflow_manifest_valid", "ok": not workflow_issues, "issue_count": len(workflow_issues)})
    if workflow_issues:
        issues.extend(f"workflow manifest validation failed: {issue}" for issue in workflow_issues)

    registry_path = expand_user_path(pack.global_registry, home)
    if not registry_path.exists():
        issues.append(f"missing global registry: {registry_path}")

    return {
        "ok": not issues,
        "issues": issues,
        "adapters": adapters,
        "level": level,
        "rules": rule_results,
    }

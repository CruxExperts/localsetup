from __future__ import annotations

from pathlib import Path

from .adapters import adapter_status, recorded_adapter_status
from .lockfile import load_json
from .manifests import load_pack_config, load_platforms
from .paths import expand_user_path, legacy_target_lockfile_path, repo_path, target_lockfile_path
from .provenance import is_managed_package, package_digest, provenance_report
from .registry import load_registry
from .workflows import validate_workflow_catalog


SUPPORTED_LEVELS = {"filesystem"}


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
    lock_path = repo_path(attachment_root, pack.lockfile, "repo.lockfile")
    if lock_path.name != "lock.json" or lock_path.parent.name != ".localsetup":
        lock_path = target_lockfile_path(attachment_root)
    lock = load_json(lock_path)
    global_root = expand_user_path(pack.global_root, home)

    issues: list[str] = []
    if not lock:
        issues.append("missing lockfile")
    legacy_lock = legacy_target_lockfile_path(attachment_root)
    if legacy_lock.exists():
        issues.append(f"legacy root lockfile remains; migrate to .localsetup/lock.json: {legacy_lock}")
    target_framework = attachment_root / "_localsetup"
    if target_framework.exists() and attachment_root.resolve(strict=False) != repo_root.resolve(strict=False):
        issues.append(f"stale target framework source is not supported: {target_framework}")
    attach_mode = lock.get("attach_mode", "symlink") if isinstance(lock, dict) else "symlink"

    if not global_root.is_dir():
        issues.append(f"missing global skill library: {global_root}")

    aliases = lock.get("aliases", {}) if isinstance(lock, dict) else {}
    for skill_name in sorted(set(aliases.values())):
        skill_path = global_root / skill_name
        if not skill_path.is_dir():
            issues.append(f"missing managed skill: {skill_path}")
        elif not is_managed_package(skill_path):
            issues.append(f"managed marker missing: {skill_path}")

    workflows = lock.get("workflows", []) if isinstance(lock, dict) else []
    for workflow_name in sorted(set(workflows)):
        workflow_path = global_root / workflow_name
        if not workflow_path.is_dir():
            issues.append(f"missing managed workflow: {workflow_path}")
        elif not is_managed_package(workflow_path):
            issues.append(f"managed marker missing: {workflow_path}")

    adapters = (
        adapter_status(repo_root, home, global_root, platform_ids=platform_ids, target_root=attachment_root)
        if platform_ids is not None
        else recorded_adapter_status(lock, global_root)
    )
    expected_by_path = {
        str(item.get("path")): item.get("packages", lock.get("repo_packages", lock.get("adapter_packages", [])))
        for item in lock.get("adapter_targets", [])
        if isinstance(item, dict)
    }
    for adapter in adapters:
        adapter.setdefault(
            "expected_packages",
            expected_by_path.get(adapter["repo_path"], lock.get("repo_packages", lock.get("adapter_packages", []))),
        )
    platform_rules = {platform.platform_id: platform.verify_rules for platform in load_platforms(repo_root)}
    rule_results: list[dict] = []
    for adapter in adapters:
        expected_mode = adapter.get("expected_mode", attach_mode)
        rules = platform_rules.get(str(adapter.get("platform")), adapter.get("verify_rules", []))
        if "adapter_path_exists" in rules or rules:
            ok = bool(adapter["exists"])
            rule_results.append({"rule": "adapter_path_exists", "platform": adapter.get("platform"), "ok": ok, "path": adapter["repo_path"]})
            if not ok:
                issues.append(f"verify rule adapter_path_exists failed: {adapter['repo_path']}")
        if "adapter_points_to_managed_root" in rules or expected_mode != "portable":
            ok = bool(adapter["points_to_global"] or adapter.get("is_scoped_symlink_adapter")) if expected_mode != "portable" else True
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
        elif expected_mode != "portable" and not (adapter["points_to_global"] or adapter.get("is_scoped_symlink_adapter")):
            issues.append(f"adapter does not point at global library: {adapter['repo_path']}")
        expected_packages = sorted(str(name) for name in adapter.get("expected_packages", []) if name)
        if expected_packages:
            visible_packages = sorted(str(name) for name in adapter.get("managed_visible_packages", adapter.get("visible_packages", [])))
            ok = visible_packages == expected_packages
            rule_results.append(
                {
                    "rule": "adapter_visible_packages_match_selection",
                    "platform": adapter.get("platform"),
                    "ok": ok,
                    "visible_count": len(visible_packages),
                    "expected_count": len(expected_packages),
                }
            )
            if not ok:
                issues.append(f"adapter visible packages do not match selection: {adapter['repo_path']}")
        integrity_failures = adapter.get("package_integrity_failures", [])
        if integrity_failures:
            rule_results.append(
                {
                    "rule": "adapter_package_targets_match_managed_root",
                    "platform": adapter.get("platform"),
                    "ok": False,
                    "failure_count": len(integrity_failures),
                    "path": adapter["repo_path"],
                }
            )
            issues.append(f"adapter package target mismatch: {adapter['repo_path']}")
        elif adapter.get("is_scoped_symlink_adapter") or adapter.get("is_portable_copy"):
            rule_results.append(
                {
                    "rule": "adapter_package_targets_match_managed_root",
                    "platform": adapter.get("platform"),
                    "ok": True,
                    "path": adapter["repo_path"],
                }
            )
        if expected_mode == "portable" and adapter.get("is_portable_copy"):
            digest_mismatches: list[str] = []
            adapter_path = Path(str(adapter["repo_path"]))
            for package_name in expected_packages or adapter.get("managed_visible_packages", []):
                package = str(package_name)
                local_digest = package_digest(adapter_path / package)
                global_digest = package_digest(global_root / package)
                if local_digest and global_digest and local_digest != global_digest:
                    digest_mismatches.append(package)
            rule_results.append(
                {
                    "rule": "portable_package_digests_match_global",
                    "platform": adapter.get("platform"),
                    "ok": not digest_mismatches,
                    "mismatches": digest_mismatches,
                    "path": adapter["repo_path"],
                }
            )
            if digest_mismatches:
                issues.append(
                    f"portable adapter package digest differs from managed library: {adapter['repo_path']}"
                )
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

    registry_path = Path(str(lock.get("registry_path"))) if isinstance(lock, dict) and lock.get("registry_path") else expand_user_path(pack.global_registry, home)
    if not registry_path.exists():
        issues.append(f"missing global registry: {registry_path}")
    registry = load_registry(registry_path) if registry_path.exists() else {}
    provenance = provenance_report(repo_root, lock=lock, registry=registry, global_root=global_root, adapters=adapters)

    return {
        "ok": not issues,
        "issues": issues,
        "provenance": provenance,
        "provenance_warnings": provenance["warnings"],
        "provenance_repair_hints": provenance["repair_hints"],
        "adapters": adapters,
        "level": level,
        "rules": rule_results,
    }

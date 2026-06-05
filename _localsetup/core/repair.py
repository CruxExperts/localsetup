from __future__ import annotations

from pathlib import Path

from .adapters import adapter_path_state, adapter_targets, legacy_global_roots
from .apply import apply_plan
from .lockfile import load_json, save_json
from .manifests import load_pack_config
from .paths import expand_user_path
from .plan import build_install_plan
from .repair_actions import _apply_pre_actions, _plan_actions
from .repair_common import _default_backup_root, _latest_version, _read_json
from .repair_inference import HISTORICAL_ADAPTERS, _infer_attach_mode, _infer_packages, _infer_platforms
from .repair_safety import _classify_stale_framework, _protected_target_reasons
from .verify import verify_install

def run_repair(
    source_root: Path,
    *,
    home: Path,
    target_root: Path | None = None,
    platform_ids: list[str] | None = None,
    backup_dir: Path | None = None,
    dependency_mode: str = "prompt-only",
    apply: bool = False,
    repair_mode: str | None = None,
    allow: list[str] | None = None,
) -> dict:
    source = source_root.expanduser().resolve(strict=False)
    target = (target_root or source).expanduser().resolve(strict=False)
    backup_root = (backup_dir or _default_backup_root(target)).expanduser().resolve(strict=False)
    warnings: list[str] = []
    blockers: list[str] = []
    decisions: list[dict] = []
    allowed = allow or []
    if repair_mode is None:
        repair_mode = "safe-repair" if apply else "report-only"
    if repair_mode == "report-only":
        apply = False
    elif repair_mode == "safe-repair":
        apply = apply or False
    elif repair_mode == "migration-plan":
        apply = False
    elif repair_mode == "apply-with-backups":
        apply = bool(apply)
    else:
        blockers.append(f"unsupported repair mode: {repair_mode}")
    modern_lock_path = target / ".localsetup" / "lock.json"
    legacy_lock_path = target / "localsetup.lock.json"
    modern_lock = _read_json(modern_lock_path, warnings, blockers, "modern lock")
    legacy_lock = _read_json(legacy_lock_path, warnings, blockers, "legacy lock")
    protected_reasons = _protected_target_reasons(source, home, target)
    inferred_platforms, platform_reasons = _infer_platforms(source, target, modern_lock, legacy_lock, platform_ids)
    attach_mode, attach_reason = _infer_attach_mode(modern_lock)
    inferred_packages = _infer_packages(source, target, home, inferred_platforms, modern_lock, legacy_lock, decisions)
    packages = list(inferred_packages.get("repo_packages", []))
    repo_skills = list(inferred_packages.get("repo_skills", []))
    repo_workflows = list(inferred_packages.get("repo_workflows", []))
    package_reasons = list(inferred_packages.get("package_reasons", []))
    pack = load_pack_config(source)
    global_root = expand_user_path(pack.global_root, home)
    stale_framework_info = _classify_stale_framework(source, home, target, protected_reasons)
    detected_shape = {
        "modern_lockfile": str(modern_lock_path) if modern_lock_path.exists() else None,
        "legacy_lockfile": str(legacy_lock_path) if legacy_lock_path.exists() else None,
        "adapter_paths": [
            str(target["repo_path"])
            for target in adapter_targets(source, home, platform_ids=inferred_platforms, target_root=target)
            if target["repo_path"].exists() or target["repo_path"].is_symlink()
        ],
        "historical_adapter_paths": [
            str(target / rel)
            for platform_id in inferred_platforms
            for rel in HISTORICAL_ADAPTERS.get(platform_id, [])
            if (target / rel).exists() or (target / rel).is_symlink()
        ],
        "stale_localsetup": str(target / "_localsetup") if (target / "_localsetup").exists() and source != target else None,
        "stale_framework": stale_framework_info,
        "legacy_global_roots": [str(path) for path in legacy_global_roots(home) if path.exists()],
        "partial_adapters": [],
        "protected_source_root": bool(protected_reasons),
        "protected_reasons": protected_reasons,
    }
    for adapter in adapter_targets(source, home, platform_ids=inferred_platforms, target_root=target):
        state = adapter_path_state(adapter["repo_path"], global_root, known_global_roots=legacy_global_roots(home))
        if state["exists"] and (state["collision_reason"] or not state["package_integrity_ok"]):
            detected_shape["partial_adapters"].append({"path": str(adapter["repo_path"]), "state": state})

    actions = _plan_actions(
        source,
        home=home,
        target_root=target,
        platform_ids=inferred_platforms,
        packages=packages,
        attach_mode=attach_mode,
        protected_reasons=protected_reasons,
        stale_framework_info=stale_framework_info,
        decisions=decisions,
        blockers=blockers,
        allow=allowed,
    )
    payload = {
        "repair_schema_version": 2,
        "ok": not blockers and not decisions,
        "applied": False,
        "source_root": str(source),
        "target_root": str(target),
        "latest_version": _latest_version(source),
        "repair_mode": repair_mode,
        "allowed": allowed,
        "detected_shape": detected_shape,
        "inferred": {
            "platforms": inferred_platforms,
            "platform_reasons": platform_reasons,
            "attach_mode": attach_mode,
            "attach_mode_reason": attach_reason,
            "repo_packages": packages,
            "repo_skills": repo_skills,
            "repo_workflows": repo_workflows,
            "custom_repo_skills": inferred_packages.get("custom_repo_skills", []),
            "package_reasons": package_reasons,
            "package_evidence": inferred_packages.get("package_evidence", []),
            "confidence": inferred_packages.get("confidence"),
            "global_package_root": str(global_root),
        },
        "actions": actions,
        "decisions": decisions,
        "backups": [],
        "verify": None,
        "blockers": blockers,
        "warnings": warnings,
        "next_actions": [],
        "metrics": {
            "blocker_count": len(blockers),
            "decision_count": len(decisions),
            "decision_kinds": sorted({str(item.get("kind")) for item in decisions}),
            "repo_package_count": len(packages),
            "repo_skill_count": len(repo_skills),
            "repo_workflow_count": len(repo_workflows),
            "custom_repo_skill_count": len(inferred_packages.get("custom_repo_skills", [])),
            "stale_framework_classification": stale_framework_info.get("classification"),
        },
    }
    if payload["decisions"]:
        payload["next_actions"].append("localsetup doctor repair --repair-mode migration-plan")
    if any(item.get("kind") == "tracked_framework_removal" for item in payload["decisions"]):
        payload["next_actions"].append(
            "localsetup doctor repair --repair-mode apply-with-backups --allow tracked-framework-removal --yes"
        )
    if payload["actions"] and not apply and not payload["decisions"]:
        payload["next_actions"].append("localsetup doctor repair --repair-mode safe-repair --yes")
    if not apply:
        return payload
    if not actions:
        return payload
    if blockers or decisions:
        backup_root.mkdir(parents=True, exist_ok=True)
        save_json(backup_root / "repair-report.json", payload)
        return payload

    backup_root.mkdir(parents=True, exist_ok=True)
    payload["backups"].extend(_apply_pre_actions(actions, backup_root, target, global_root, legacy_global_roots(home)))
    plan = build_install_plan(
        source,
        home=home,
        global_preset="core",
        repo_preset="custom",
        repo_skills=repo_skills,
        repo_workflows=repo_workflows,
        attach_mode=attach_mode,
        platform_ids=inferred_platforms,
        target_root=target,
    )
    install = apply_plan(source, plan, home=home, dry_run=False, target_root=target)
    payload["install"] = install
    lock = load_json(target / ".localsetup" / "lock.json")
    migration_backup = lock.get("migration_origin", {}).get("backup") if isinstance(lock, dict) else None
    if migration_backup:
        payload["backups"].append(str(migration_backup))
    payload["verify"] = verify_install(source, home=home, platform_ids=inferred_platforms, target_root=target)
    payload["ok"] = bool(payload["verify"]["ok"])
    payload["applied"] = True
    save_json(backup_root / "repair-report.json", payload)
    payload["report"] = str(backup_root / "repair-report.json")
    return payload

from __future__ import annotations

from pathlib import Path

from .adapters import adapter_path_state, adapter_targets, legacy_global_roots
from .apply import apply_plan
from .lockfile import load_json, save_json
from .manifests import load_pack_config
from .paths import expand_user_path
from .path_contract import paths_manifest_issues, paths_manifest_path, write_paths_manifest
from .plan import build_install_plan
from .repair_actions import _apply_pre_actions, _plan_actions
from .repair_common import _default_backup_root, _latest_version, _read_json
from .repair_inference import HISTORICAL_ADAPTERS, _infer_attach_mode, _infer_packages, _infer_platforms
from .repair_safety import _classify_stale_framework, _protected_target_reasons
from .verify import verify_install
from .repair_personal_route import personal_repair_route

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
    return _run_repair(source_root, home=home, target_root=target_root, platform_ids=platform_ids,
                       backup_dir=backup_dir, dependency_mode=dependency_mode, apply=apply,
                       repair_mode=repair_mode, allow=allow)


def _run_repair(
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
    _lock_held: dict | None = None,
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
    recorded_scope = (modern_lock if modern_lock_path.exists() else legacy_lock).get("skill_scope", "repo")
    if recorded_scope in ("personal", "both"):
        if _lock_held:
            return {'ok': False, 'applied': False, 'actions': [], 'warnings': warnings,
                    'repair_mode': repair_mode, 'blockers': ['Recorded skill scope changed while acquiring repair lock; re-run repair']}
        return personal_repair_route(
            source, home, target, modern_lock if modern_lock_path.exists() else legacy_lock,
            clients=platform_ids, apply=apply, mode=repair_mode, allowed=allowed,
            warnings=warnings, blockers=blockers,
        )
    if apply and not _lock_held:
        from .locking import package_root_lock
        from .paths import global_layout
        with package_root_lock(global_layout(home).localsetup_home) as held_lock:
            return _run_repair(source, home=home, target_root=target, platform_ids=platform_ids,
                               backup_dir=backup_root, dependency_mode=dependency_mode, apply=apply,
                               repair_mode=repair_mode, allow=allowed, _lock_held=held_lock)
    from .retained_update import retained_repository_clients
    recorded_lock = modern_lock if modern_lock_path.exists() else legacy_lock
    if retained_repository_clients(source, recorded_lock):
        return {"ok": False, "applied": False, "skill_scope": "repo", "actions": [],
                "warnings": warnings, "decisions": [], "repair_mode": repair_mode,
                "inferred": {"platforms": recorded_lock.get("platforms", [])},
                "blockers": [*blockers, "Retained repository adapters require recorded-path manual recovery; automatic repair is not qualified. Preserve the receipt and adapter content; do not infer replacement clients."]}
    protected_reasons = _protected_target_reasons(source, home, target)
    inferred_platforms, platform_reasons = _infer_platforms(source, target, modern_lock, legacy_lock, platform_ids)
    from .mutable_ownership import require_owned_copies
    recorded_paths = [row['path'] for row in recorded_lock.get('adapter_targets', [])
                      if set(row.get('platforms') or [row.get('platform')]).intersection(inferred_platforms)]
    planned_paths = [row['repo_path'] for row in adapter_targets(source, home, inferred_platforms, target_root=target)]
    try:mutable_paths = require_owned_copies(source, home, [*recorded_paths, *planned_paths], target=target)
    except ValueError as exc:
        return {'ok': False, 'applied': False, 'skill_scope': 'repo', 'actions': [],
                'warnings': warnings, 'decisions': [], 'repair_mode': repair_mode,
                'inferred': {'platforms': inferred_platforms}, 'blockers': [*blockers, str(exc)]}
    attach_mode, attach_reason = _infer_attach_mode(recorded_lock)
    if mutable_paths and attach_mode != 'portable':
        from .adapter_markers import adapter_marker_state
        modes = {adapter_marker_state(Path(path))['mode'] for path in planned_paths
                 if Path(path).exists() or Path(path).is_symlink()}
        if 'attach_mode' in recorded_lock or modes - {'portable'}:
            return {'ok': False, 'applied': False, 'actions': [], 'warnings': warnings,
                    'repair_mode': repair_mode, 'blockers': ['Recorded mutable adapters conflict with inferred repair mode; preserve their ownership and copies']}
        attach_mode, attach_reason = 'portable', 'recorded mutable ownership requires independent portable copies'
    inferred_packages = _infer_packages(source, target, home, inferred_platforms, modern_lock, legacy_lock, decisions)
    packages = list(inferred_packages.get("repo_packages", []))
    repo_skills = list(inferred_packages.get("repo_skills", []))
    repo_workflows = list(inferred_packages.get("repo_workflows", []))
    package_reasons = list(inferred_packages.get("package_reasons", []))
    pack = load_pack_config(source)
    global_root = expand_user_path(pack.global_root, home)
    stale_framework_info = _classify_stale_framework(source, home, target, protected_reasons)
    resolver_issues = paths_manifest_issues(source, home)
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
        "stale_framework_path": str(target / "ls") if (target / "ls").exists() and source != target else None,
        "stale_framework": stale_framework_info,
        "legacy_global_roots": [str(path) for path in legacy_global_roots(home) if path.exists()],
        "partial_adapters": [],
        "protected_source_root": bool(protected_reasons),
        "protected_reasons": protected_reasons,
    }
    for adapter in adapter_targets(source, home, platform_ids=inferred_platforms, target_root=target):
        state = adapter_path_state(
            adapter["repo_path"],
            global_root,
            known_global_roots=legacy_global_roots(home),
            target_root=target,
        )
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
    resolver_action = {
        "kind": "refresh_paths_manifest",
        "path": str(paths_manifest_path(home)),
        "safety": "safe",
        "reason": "resolver manifest is missing or stale",
        "details": {"issues": resolver_issues},
    }
    if resolver_issues:
        actions.append(resolver_action)
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
        "resolver": {
            "ok": not resolver_issues,
            "issues": resolver_issues,
            "manifest": str(paths_manifest_path(home)),
        },
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
    if resolver_issues:
        payload["paths_manifest"] = write_paths_manifest(source, home)["manifest"]
        refreshed_resolver_issues = paths_manifest_issues(source, home)
        payload["resolver"] = {
            "ok": not refreshed_resolver_issues,
            "issues": refreshed_resolver_issues,
            "manifest": str(paths_manifest_path(home)),
        }
    pre_actions = [action for action in actions if action.get("kind") != "refresh_paths_manifest"]
    if not pre_actions:
        payload["ok"] = True
        payload["applied"] = True
        payload["report"] = str(backup_root / "repair-report.json")
        save_json(backup_root / "repair-report.json", payload)
        return payload
    payload["backups"].extend(_apply_pre_actions(pre_actions, backup_root, target, global_root, legacy_global_roots(home)))
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
    if _lock_held:
        from .apply import _apply_plan_unlocked
        install = _apply_plan_unlocked(source, plan, home=home, dry_run=False, target_root=target)
        install["package_root_lock"] = _lock_held
    else:
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

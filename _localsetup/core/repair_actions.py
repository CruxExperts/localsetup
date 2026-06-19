"""Repair action planning and pre-apply helpers."""

from __future__ import annotations

from pathlib import Path
import shutil

from .aliases import collect_skill_aliases
from .adapters import ADAPTER_MARKER_JSON, adapter_path_state, adapter_targets, legacy_global_roots, remove_managed_adapter_entries
from .git_state import git_untrack_path, inspect_path
from .manifests import load_pack_config
from .migration import _backup_item
from .paths import expand_user_path
from .provenance import is_managed_package
from .repair_inference import HISTORICAL_ADAPTERS
from .repair_safety import _localsetup_owned_adapter_dir, _symlink_target_under_managed_roots

def _action(kind: str, path: Path, *, safety: str, reason: str, details: dict | None = None) -> dict:
    return {
        "kind": kind,
        "path": str(path),
        "safety": safety,
        "reason": reason,
        "details": details or {},
    }

def _remove_path(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)

def _plan_actions(
    source_root: Path,
    *,
    home: Path,
    target_root: Path,
    platform_ids: list[str],
    packages: list[str],
    attach_mode: str,
    protected_reasons: list[str],
    stale_framework_info: dict[str, Any],
    decisions: list[dict],
    blockers: list[str],
    allow: list[str],
) -> list[dict]:
    actions: list[dict] = []
    pre_action_count = 0
    legacy_lock = target_root / "localsetup.lock.json"
    if legacy_lock.exists() or legacy_lock.is_symlink():
        actions.append(
            _action(
                "backup_remove_legacy_lock",
                legacy_lock,
                safety="safe",
                reason="modern lock path is .localsetup/lock.json",
            )
        )
        pre_action_count += 1

    stale_framework = target_root / "_localsetup"
    stale_class = stale_framework_info.get("classification")
    if stale_class and stale_class != "absent":
        if stale_class == "protected_source_root":
            decisions.append(
                {
                    "kind": "protected_source_root",
                    "code": "protected_source_root",
                    "path": str(target_root),
                    "reason": "target is a legitimate Localsetup source location",
                    "values": protected_reasons,
                    "required": "do not remove or replace target _localsetup from doctor repair",
                    "prompt_hint": "Use maintainer/source checkout commands instead of target repair.",
                }
            )
        elif stale_class == "clean_tracked_stale_framework":
            actions.append(
                _action(
                    "git_untrack_stale_framework",
                    stale_framework,
                    safety="safe",
                    reason="clean tracked consumer _localsetup framework source can be untracked before removal",
                    details={"tracked_entries": stale_framework_info.get("tracked_entries", [])},
                )
            )
            actions.append(
                _action(
                    "backup_remove_stale_framework",
                    stale_framework,
                    safety="safe",
                    reason="consumer repo should not keep copied _localsetup framework source",
                )
            )
            pre_action_count += 1
        elif stale_class == "untracked_stale_framework":
            actions.append(
                _action(
                    "backup_remove_stale_framework",
                    stale_framework,
                    safety="safe",
                    reason="consumer repo should not keep copied _localsetup framework source",
                )
            )
            pre_action_count += 1
        elif stale_class == "dirty_stale_framework":
            decisions.append(
                {
                    "kind": "stale_framework",
                    "code": "dirty_stale_framework",
                    "path": str(stale_framework),
                    "reason": "framework-like _localsetup has Git changes or mixed tracked/untracked state",
                    "required": "review migration plan before removal",
                    "prompt_hint": "Inspect Git state under _localsetup and decide whether content is user-owned.",
                }
            )
        elif stale_class == "custom_localsetup_content":
            decisions.append(
                {
                    "kind": "stale_framework",
                    "code": "custom_localsetup_content",
                    "path": str(stale_framework),
                    "reason": "_localsetup does not look like Localsetup framework source",
                    "values": stale_framework_info.get("unknown_entries", []),
                    "required": "review this directory before repair can remove it",
                    "prompt_hint": "Preserve or migrate custom _localsetup content before running repair.",
                }
            )
        elif stale_class == "unsafe_framework_node":
            decisions.append(
                {
                    "kind": "stale_framework",
                    "code": "unsafe_framework_node",
                    "path": str(stale_framework),
                    "reason": "_localsetup is not a supported directory node",
                    "required": "review this filesystem node manually",
                    "prompt_hint": "Do not delete symlinks or special nodes without human review.",
                }
            )
        elif _framework_source_like(stale_framework):
            tracked = _is_tracked(target_root, stale_framework)
            if tracked and "tracked-framework-removal" in allow:
                actions.append(
                    _action(
                        "git_untrack_stale_framework",
                        stale_framework,
                        safety="safe",
                        reason="tracked consumer _localsetup framework source removal explicitly allowed",
                    )
                )
                actions.append(
                    _action(
                        "backup_remove_stale_framework",
                        stale_framework,
                        safety="safe",
                        reason="tracked consumer _localsetup framework source removal explicitly allowed",
                    )
                )
                pre_action_count += 1
            else:
                actions.append(
                    _action(
                        "backup_remove_stale_framework",
                        stale_framework,
                        safety="safe",
                        reason="consumer repo should not keep copied _localsetup framework source",
                    )
                )
                pre_action_count += 1
        else:
            decisions.append(
                {
                    "kind": "stale_framework",
                    "path": str(stale_framework),
                    "reason": "_localsetup does not look like Localsetup framework source",
                    "required": "review this directory before repair can remove it",
                }
            )

    pack = load_pack_config(source_root)
    global_root = expand_user_path(pack.global_root, home)
    known_roots = legacy_global_roots(home)
    managed_roots = [global_root, *known_roots]
    selected_packages = set(packages)
    aliases = collect_skill_aliases(source_root / "_localsetup" / "skills")
    legacy_alias_entries = set(aliases) | set(aliases.values())
    current_adapter_targets: set[Path] = set()
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        path = target["repo_path"]
        if path.is_symlink() and path.exists():
            current_adapter_targets.add(path.resolve(strict=False))
        state = adapter_path_state(path, global_root, known_global_roots=known_roots, target_root=target_root)
        same_name_custom = selected_packages & (set(state.get("custom_entries", [])) | set(state.get("unknown_entries", [])))
        if same_name_custom:
            decisions.append(
                {
                    "kind": "adapter_content",
                    "path": str(path),
                    "reason": "adapter contains custom or unknown entries with selected Localsetup package names",
                    "values": sorted(same_name_custom),
                    "required": "move or rename this content before doctor repair can recreate the adapter",
                }
            )
            continue
        reason = state["collision_reason"]
        if reason in {"dangling symlink"}:
            if _symlink_target_under_managed_roots(path, managed_roots):
                actions.append(_action("backup_remove_adapter", path, safety="safe", reason=f"repairable Localsetup-owned adapter collision: {reason}"))
                pre_action_count += 1
            else:
                decisions.append(
                    {
                        "kind": "adapter_collision",
                        "path": str(path),
                        "reason": reason,
                        "required": "review this symlink before applying repair",
                    }
                )
        elif reason == "unmanaged adapter directory":
            if _localsetup_owned_adapter_dir(source_root, path, decisions):
                actions.append(
                    _action(
                        "backup_remove_adapter",
                        path,
                        safety="safe",
                        reason="adapter directory contains only Localsetup-owned or alias-mappable packages but lacks marker",
                    )
                )
                pre_action_count += 1
        elif reason:
            decisions.append(
                {
                    "kind": "adapter_collision",
                    "path": str(path),
                    "reason": reason,
                    "required": "move or review this path before applying repair",
                }
            )
        elif state["exists"] and not state["package_integrity_ok"]:
            actions.append(
                _action(
                    "remove_managed_adapter_entries",
                    path,
                    safety="safe",
                    reason="refresh Localsetup-managed adapter metadata and package entries while preserving custom content",
                    details={"packages": packages},
                )
            )
            pre_action_count += 1

    for platform_id, rel_paths in HISTORICAL_ADAPTERS.items():
        if platform_id not in platform_ids:
            continue
        for rel in rel_paths:
            path = target_root / rel
            if not (path.exists() or path.is_symlink()):
                continue
            if path.resolve(strict=False) in current_adapter_targets:
                continue
            state = adapter_path_state(path, global_root, known_global_roots=known_roots, target_root=target_root)
            custom_entries = set(state.get("custom_entries", []))
            if state["status_code"] == "custom_repo_skills" and not (custom_entries & legacy_alias_entries):
                continue
            if (path.is_symlink() and _symlink_target_under_managed_roots(path, managed_roots)) or _localsetup_owned_adapter_dir(source_root, path, decisions):
                actions.append(
                    _action(
                        "backup_remove_historical_adapter",
                        path,
                        safety="safe",
                        reason=f"historical {platform_id} adapter path is superseded by current platform adapter",
                    )
                )
                pre_action_count += 1

    lock_exists = (target_root / ".localsetup" / "lock.json").is_file()
    adapters_modern = True
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        state = adapter_path_state(
            target["repo_path"],
            global_root,
            known_global_roots=known_roots,
            target_root=target_root,
        )
        if not (
            state["is_scoped_symlink_adapter"] or state.get("is_repo_local_symlink_adapter")
        ) or not state["package_integrity_ok"]:
            adapters_modern = False
            break
    if pre_action_count == 0 and lock_exists and (not platform_ids or adapters_modern):
        return actions

    if platform_ids:
        for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
            actions.append(
                _action(
                    "install_adapter",
                    target["repo_path"],
                    safety="safe",
                    reason="create current scoped adapter from inferred Localsetup package selection",
                    details={"platform": target["platform"], "mode": attach_mode, "packages": packages},
                )
            )
    actions.append(
        _action(
            "write_lock",
            target_root / ".localsetup" / "lock.json",
            safety="safe",
            reason="record modern Localsetup target state",
        )
    )
    if protected_reasons and actions:
        decisions.append(
            {
                "kind": "protected_source_root",
                "path": str(target_root),
                "reason": "repair would modify a legitimate Localsetup source location",
                "values": protected_reasons,
                "required": "run install or maintainer commands explicitly from the source checkout instead",
            }
        )
    if blockers:
        return actions
    return actions

def _apply_pre_actions(actions: list[dict], backup_root: Path, target_root: Path, global_root: Path, known_roots: list[Path]) -> list[str]:
    backups: list[str] = []
    removable = {
        "backup_remove_stale_framework",
        "backup_remove_adapter",
        "backup_remove_historical_adapter",
        "remove_managed_adapter_entries",
    }
    for action in actions:
        if action["kind"] == "git_untrack_stale_framework":
            continue
        if action["kind"] not in removable:
            continue
        path = Path(action["path"])
        if not (path.exists() or path.is_symlink()):
            continue
        if action["kind"] == "remove_managed_adapter_entries":
            backups.append(_backup_item(path, backup_root, target_root))
            remove_managed_adapter_entries(
                path,
                global_root,
                known_global_roots=known_roots,
                recorded_packages=action.get("details", {}).get("packages", []),
            )
            continue
        backups.append(_backup_item(path, backup_root, target_root))
        if action["kind"] == "backup_remove_stale_framework" and path.name == "_localsetup":
            git_state = inspect_path(target_root, "_localsetup")
            if git_state.get("tracked_entries"):
                result = git_untrack_path(target_root, "_localsetup")
                if not result["ok"]:
                    raise RuntimeError(f"failed to untrack _localsetup before removal: {result['stderr'] or result['stdout']}")
        _remove_path(path)
    return backups

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .adapters import ADAPTER_MARKER_JSON, adapter_path_state, adapter_targets, legacy_global_roots, remove_managed_adapter_entries
from .aliases import collect_skill_aliases, skill_alias
from .apply import apply_plan
from .git_state import git_untrack_path, inspect_path
from .lockfile import load_json, save_json
from .manifests import load_pack_config, load_platforms
from .migration import _backup_item
from .paths import expand_user_path
from .plan import build_install_plan
from .provenance import is_managed_package
from .selection import resolve_package_selection
from .shell import shell_registration_status
from .skills import load_skill_catalog
from .verify import verify_install
from .workflows import load_workflow_catalog


HISTORICAL_ADAPTERS = {
    "codex": [".agents/skills"],
}


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _default_backup_root(target_root: Path) -> Path:
    return target_root / ".localsetup" / "backups" / f"repair-{_stamp()}"


def _read_json(path: Path, warnings: list[str], blockers: list[str], label: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        blockers.append(f"{label} is not readable JSON: {path}: {exc}")
        return {}
    if not isinstance(payload, dict):
        blockers.append(f"{label} is not a JSON object: {path}")
        return {}
    return payload


def _latest_version(source_root: Path) -> str | None:
    version_path = source_root / "VERSION"
    try:
        return version_path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _known_package_names(source_root: Path) -> set[str]:
    skill_names = {skill.name for skill in load_skill_catalog(source_root)}
    workflow_root = source_root / "_localsetup" / "workflows"
    workflow_names = {path.name for path in workflow_root.iterdir() if path.is_dir()} if workflow_root.exists() else set()
    return skill_names | workflow_names


def _known_skill_names(source_root: Path) -> set[str]:
    return {skill.name for skill in load_skill_catalog(source_root)}


def _known_workflow_names(source_root: Path) -> set[str]:
    return {workflow.package for workflow in load_workflow_catalog(source_root)}


def _normalize_package_names(source_root: Path, values: list[str], decisions: list[dict]) -> dict[str, Any]:
    known = _known_skill_names(source_root)
    known_workflows = _known_workflow_names(source_root)
    known_packages = _known_package_names(source_root)
    aliases = collect_skill_aliases(source_root / "_localsetup" / "skills")
    normalized: list[str] = []
    normalized_skills: list[str] = []
    normalized_workflows: list[str] = []
    unknown: list[str] = []
    evidence: list[dict[str, str]] = []
    for value in values:
        name = str(value).strip()
        if not name:
            continue
        canonical = aliases.get(name, name)
        if canonical not in known_packages:
            alias_candidate = aliases.get(skill_alias(name), skill_alias(name))
            canonical = alias_candidate if alias_candidate in known_packages else canonical
        if canonical in known_packages:
            if canonical not in normalized:
                normalized.append(canonical)
            if canonical in known and canonical not in normalized_skills:
                normalized_skills.append(canonical)
            if canonical in known_workflows and canonical not in normalized_workflows:
                normalized_workflows.append(canonical)
            evidence.append({"value": name, "canonical": canonical, "kind": "workflow" if canonical in known_workflows else "skill"})
        else:
            unknown.append(name)
    if unknown:
        decisions.append(
            {
                "kind": "package_selection",
                "code": "unknown_package_selection",
                "reason": "visible package selection contains unknown or unmanaged names",
                "values": sorted(set(unknown)),
                "required": "choose explicit repo package selectors before applying repair",
            }
        )
    return {
        "repo_packages": normalized,
        "repo_skills": normalized_skills,
        "repo_workflows": normalized_workflows,
        "package_evidence": evidence,
    }


def _extract_list(payload: dict[str, Any], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        raw = payload.get(key)
        if isinstance(raw, list):
            values.extend(str(item) for item in raw)
    return values


def _path_hints_platform(path_text: str) -> str | None:
    normalized = path_text.replace("\\", "/")
    if ".agents/skills" in normalized or ".codex/skills" in normalized:
        return "codex"
    if ".claude/skills" in normalized:
        return "claude-code"
    if ".cursor/skills" in normalized:
        return "cursor"
    if ".kilo/skills" in normalized:
        return "kilo"
    if ".opencode/skills" in normalized:
        return "opencode"
    if ".openclaw/skills" in normalized:
        return "openclaw"
    return None


def _visible_names(path: Path) -> list[str]:
    if not path.is_dir() or path.is_symlink():
        return []
    return sorted(child.name for child in path.iterdir() if not child.name.startswith("."))


def _visible_package_entries(path: Path) -> list[dict[str, Any]]:
    if not path.is_dir() or path.is_symlink():
        return []
    entries: list[dict[str, Any]] = []
    for child in sorted(path.iterdir()):
        if child.name.startswith("."):
            continue
        entries.append(
            {
                "name": child.name,
                "path": str(child),
                "custom_skill": child.is_dir() and not child.is_symlink() and (child / "SKILL.md").is_file(),
            }
        )
    return entries


def _infer_platforms(
    source_root: Path,
    target_root: Path,
    modern_lock: dict[str, Any],
    legacy_lock: dict[str, Any],
    explicit_platforms: list[str] | None,
) -> tuple[list[str], list[str]]:
    if explicit_platforms is not None:
        return sorted(set(explicit_platforms)), ["explicit --platforms"]
    selected: set[str] = set()
    reasons: list[str] = []
    for value in _extract_list(modern_lock, "platforms"):
        selected.add(value)
    if selected:
        reasons.append(".localsetup/lock.json platforms")
    for value in _extract_list(legacy_lock, "platforms", "tools"):
        selected.add(value)
    for value in _extract_list(legacy_lock, "adapter_state", "adapter_paths"):
        platform_id = _path_hints_platform(value)
        if platform_id:
            selected.add(platform_id)
    if selected:
        reasons.append("legacy lock selectors")
    known_platforms = {platform.platform_id: platform for platform in load_platforms(source_root)}
    for platform in known_platforms.values():
        for rel in platform.repo_paths:
            if (target_root / rel).exists() or (target_root / rel).is_symlink():
                selected.add(platform.platform_id)
                reasons.append(f"existing adapter path {rel}")
    for platform_id, rel_paths in HISTORICAL_ADAPTERS.items():
        for rel in rel_paths:
            if (target_root / rel).exists() or (target_root / rel).is_symlink():
                selected.add(platform_id)
                reasons.append(f"historical adapter path {rel}")
    known_ids = set(known_platforms)
    return sorted(selected & known_ids), sorted(set(reasons))


def _infer_attach_mode(modern_lock: dict[str, Any]) -> tuple[str, str]:
    if modern_lock.get("attach_mode") == "portable":
        return "portable", "modern lock attach_mode"
    return "symlink", "default modern scoped symlink adapters"


def _infer_packages(
    source_root: Path,
    target_root: Path,
    home: Path,
    platform_ids: list[str],
    modern_lock: dict[str, Any],
    legacy_lock: dict[str, Any],
    decisions: list[dict],
) -> dict[str, Any]:
    values: list[str] = []
    reasons: list[str] = []
    custom_repo_skills: list[dict[str, str]] = []
    for key in ("repo_packages", "adapter_packages", "repo_skills"):
        extracted = _extract_list(modern_lock, key)
        if extracted:
            values.extend(extracted)
            reasons.append(f"modern lock {key}")
    extracted_workflows = _extract_list(modern_lock, "repo_workflows", "workflows")
    if extracted_workflows:
        values.extend(extracted_workflows)
        reasons.append("modern lock repo_workflows/workflows")
    for key in ("repo_packages", "adapter_packages", "installed_skills", "skills", "packs"):
        extracted = _extract_list(legacy_lock, key)
        if extracted:
            values.extend(extracted)
            reasons.append(f"legacy lock {key}")
    extracted_legacy_workflows = _extract_list(legacy_lock, "repo_workflows", "workflows", "installed_workflows")
    if extracted_legacy_workflows:
        values.extend(extracted_legacy_workflows)
        reasons.append("legacy lock repo_workflows/workflows")
    pack_names = set(load_pack_config(source_root).packs)
    values = [value for value in values if value not in pack_names]
    known_packages = _known_package_names(source_root)
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        entries = _visible_package_entries(target["repo_path"])
        visible = [entry["name"] for entry in entries if entry["name"] in known_packages]
        custom_repo_skills.extend(
            {"name": entry["name"], "path": entry["path"]}
            for entry in entries
            if entry["name"] not in known_packages and entry["custom_skill"]
        )
        if visible:
            values.extend(visible)
            reasons.append(f"visible adapter packages at {target['repo_path'].relative_to(target_root)}")
    for rel_paths in HISTORICAL_ADAPTERS.values():
        for rel in rel_paths:
            entries = _visible_package_entries(target_root / rel)
            visible = [entry["name"] for entry in entries if entry["name"] in known_packages]
            custom_repo_skills.extend(
                {"name": entry["name"], "path": entry["path"]}
                for entry in entries
                if entry["name"] not in known_packages and entry["custom_skill"]
            )
            if visible:
                values.extend(visible)
                reasons.append(f"visible historical adapter packages at {rel}")
    normalized = _normalize_package_names(source_root, values, decisions)
    if normalized["repo_packages"]:
        normalized["package_reasons"] = sorted(set(reasons))
        normalized["custom_repo_skills"] = sorted(custom_repo_skills, key=lambda item: (item["name"], item["path"]))
        normalized["confidence"] = "high"
        return normalized
    default = resolve_package_selection(source_root, preset="core", target_root=target_root).packages
    default_normalized = _normalize_package_names(source_root, default, decisions)
    default_normalized["package_reasons"] = ["default core selection"]
    default_normalized["custom_repo_skills"] = sorted(custom_repo_skills, key=lambda item: (item["name"], item["path"]))
    default_normalized["confidence"] = "default"
    return default_normalized


def _localsetup_owned_adapter_dir(source_root: Path, path: Path, decisions: list[dict]) -> bool:
    if not path.is_dir() or path.is_symlink():
        return False
    unmanaged: list[str] = []
    for child in sorted(path.iterdir()):
        if child.name in {ADAPTER_MARKER_JSON, ".localsetup-portable"}:
            continue
        if child.name.startswith("."):
            unmanaged.append(child.name)
            continue
        if child.is_dir() and not child.is_symlink() and is_managed_package(child):
            continue
        unmanaged.append(child.name)
    if unmanaged:
        decisions.append(
            {
                "kind": "adapter_content",
                "path": str(path),
                "reason": "adapter directory contains non-Localsetup files",
                "values": unmanaged,
                "required": "move or classify this content before applying repair",
            }
        )
        return False
    return True


def _symlink_target_under_managed_roots(path: Path, managed_roots: list[Path]) -> bool:
    if not path.is_symlink():
        return False
    link_target = path.readlink()
    if not link_target.is_absolute():
        link_target = path.parent / link_target
    resolved_target = link_target.resolve(strict=False)
    for root in managed_roots:
        resolved_root = root.resolve(strict=False)
        if resolved_target == resolved_root:
            return True
        try:
            resolved_target.relative_to(resolved_root)
            return True
        except ValueError:
            continue
    return False


def _framework_source_like(path: Path) -> bool:
    return (path / "config" / "pack.yaml").is_file() and (path / "core").is_dir()


def _relative_file_set(path: Path) -> set[str]:
    if not path.is_dir() or path.is_symlink():
        return set()
    files: set[str] = set()
    for child in path.rglob("*"):
        if child.is_dir():
            continue
        try:
            rel = child.relative_to(path).as_posix()
        except ValueError:
            continue
        files.add(rel)
    return files


def _differing_files(left: Path, right: Path, rel_paths: set[str]) -> list[str]:
    differing: list[str] = []
    for rel in sorted(rel_paths):
        try:
            if (left / rel).read_bytes() != (right / rel).read_bytes():
                differing.append(rel)
        except OSError:
            differing.append(rel)
    return differing


def _source_root_like(path: Path) -> bool:
    framework = path / "_localsetup"
    return (
        _framework_source_like(framework)
        and (path / "VERSION").is_file()
        and ((path / "pyproject.toml").is_file() or (path / "install").is_file())
    )


def _is_tracked(target_root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(target_root)
    except ValueError:
        return False
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", str(rel)],
        cwd=target_root,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _classify_stale_framework(source_root: Path, home: Path, target_root: Path, protected_reasons: list[str]) -> dict[str, Any]:
    path = target_root / "_localsetup"
    exists = path.exists() or path.is_symlink()
    git_state = inspect_path(target_root, "_localsetup") if exists else {
        "supported": False,
        "tracked_entries": [],
        "staged_entries": [],
        "unstaged_entries": [],
        "untracked_entries": [],
        "ignored_entries": [],
        "status_entries": [],
        "clean": False,
        "dirty": False,
        "error": None,
    }
    info: dict[str, Any] = {
        "path": str(path),
        "classification": "absent",
        "framework_like": False,
        "protected": False,
        "git_state": git_state,
        "tracked_entries": git_state.get("tracked_entries", []),
        "unknown_entries": [],
        "removable": False,
        "required_mode": None,
        "evidence": [],
    }
    if not exists or source_root.resolve(strict=False) == target_root.resolve(strict=False):
        return info
    if protected_reasons:
        info.update(
            {
                "classification": "protected_source_root",
                "protected": True,
                "evidence": protected_reasons,
            }
        )
        return info
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        info.update({"classification": "unsafe_framework_node", "evidence": ["_localsetup is not a directory"]})
        return info
    if not _framework_source_like(path):
        unknown = []
        if path.is_dir():
            unknown = sorted(child.name for child in path.iterdir() if not child.name.startswith("."))
        info.update(
            {
                "classification": "custom_localsetup_content",
                "unknown_entries": unknown,
                "evidence": ["_localsetup does not match Localsetup framework source shape"],
            }
        )
        return info
    target_files = _relative_file_set(path)
    source_framework = source_root / "_localsetup"
    source_files = _relative_file_set(source_framework)
    extra_files = sorted(target_files - source_files)
    modified_files = _differing_files(path, source_framework, target_files & source_files)
    if extra_files or modified_files:
        info.update(
            {
                "classification": "custom_localsetup_content",
                "framework_like": True,
                "unknown_entries": extra_files,
                "modified_entries": modified_files,
                "evidence": ["framework-shaped _localsetup differs from the current Localsetup source tree"],
            }
        )
        return info
    tracked = bool(git_state.get("tracked_entries"))
    dirty = bool(
        git_state.get("staged_entries")
        or git_state.get("unstaged_entries")
        or (tracked and git_state.get("untracked_entries"))
    )
    info["framework_like"] = True
    if dirty:
        info.update(
            {
                "classification": "dirty_stale_framework",
                "required_mode": "migration-plan",
                "evidence": ["Git reports staged, unstaged, or mixed untracked changes under _localsetup"],
            }
        )
        return info
    if tracked:
        info.update(
            {
                "classification": "clean_tracked_stale_framework",
                "removable": True,
                "required_mode": "safe-repair",
                "evidence": ["tracked _localsetup is framework-like and clean"],
            }
        )
        return info
    info.update(
        {
            "classification": "untracked_stale_framework",
            "removable": True,
            "required_mode": "safe-repair",
            "evidence": ["untracked _localsetup is framework-like"],
        }
    )
    return info


def _protected_source_roots(source_root: Path, home: Path) -> list[dict]:
    roots: list[dict] = [
        {"path": source_root.resolve(strict=False), "reason": "active source root"},
        {
            "path": (home / ".local" / "share" / "localsetup" / "source").resolve(strict=False),
            "reason": "default managed Localsetup source checkout",
        },
    ]
    shell_status = shell_registration_status(source_root, home=home)
    recorded_source = shell_status.get("source_root")
    if recorded_source:
        roots.append(
            {
                "path": Path(str(recorded_source)).expanduser().resolve(strict=False),
                "reason": "registered Localsetup shell source checkout",
            }
        )
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in roots:
        key = str(item["path"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _protected_target_reasons(source_root: Path, home: Path, target_root: Path) -> list[str]:
    resolved_target = target_root.resolve(strict=False)
    reasons = [
        item["reason"]
        for item in _protected_source_roots(source_root, home)
        if Path(item["path"]).resolve(strict=False) == resolved_target
    ]
    if _source_root_like(target_root):
        reasons.append("target looks like a Localsetup maintainer/source checkout")
    return sorted(set(reasons))


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
    for target in adapter_targets(source_root, home, platform_ids=platform_ids, target_root=target_root):
        path = target["repo_path"]
        state = adapter_path_state(path, global_root, known_global_roots=known_roots)
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
        state = adapter_path_state(target["repo_path"], global_root, known_global_roots=known_roots)
        if not state["is_scoped_symlink_adapter"] or not state["package_integrity_ok"]:
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

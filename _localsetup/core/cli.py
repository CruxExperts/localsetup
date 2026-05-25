from __future__ import annotations

import argparse
import os
import json
from importlib.resources import files
from pathlib import Path
import subprocess
import sys
import time

from .adapters import adapter_path_state, adapter_status, recorded_adapter_status
from .apply import apply_plan
from .config import DEPENDENCY_MODES, InstallConfig, config_to_dict, load_install_config, merge_cli_config
from .context import build_agent_context, render_markdown_report
from .conversion import convert_repo
from .dependencies import ensure_dependencies
from .diffing import diff_plan_current
from .doctor import run_doctor
from .docs import generate_alias_outputs
from .global_first_audit import audit_global_first
from .git_state import git_status_snapshot, status_delta
from .harness import disable as harness_disable
from .harness import enable as harness_enable
from .harness import init as harness_init
from .harness import payload_to_text as harness_payload_to_text
from .harness import plan as harness_plan
from .harness import run as harness_run
from .harness import status as harness_status
from .repo_finalizer import payload_to_text as repo_finalizer_payload_to_text
from .repo_finalizer import plan as repo_finalizer_plan
from .repo_finalizer import run as repo_finalizer_run
from .repo_finalizer import status as repo_finalizer_status
from .hooks import run_maintainer_gate
from .inventory import install_inventory
from .manifests import load_pack_config
from .manifests import load_platforms
from .manifests import validate_manifest_schemas
from .lockfile import load_json, save_json, save_text
from .handoff import agent_prompt_payload
from .health import read_health_status, repair_queue, write_health_event, write_repair_queue_prompts
from .locking import PackageRootLockTimeout
from .migration import conservative_migrate, scan_legacy_references
from .package import build_public_artifact, verify_release_artifact, write_installed_sbom, write_source_sbom
from .paths import expand_user_path
from .plugin_packs import build_codex_plugins, load_plugin_pack_configs, plan_plugin_packs, validate_codex_plugin_path, validate_plugin_pack_manifest
from .plan import build_install_plan
from .provenance import provenance_report
from .query import adopt_recommendations, graph_payload, pack_reasoning, skill_payload, workflow_payload
from .repair import run_repair
from .registry import load_registry
from .rollback import rollback
from .selection import PRESETS
from .shell import SHIM_ENV, detect_invocation_target, register_shell_command, shell_registration_status
from .skills import load_skill_catalog, validate_skill_catalog
from .skills import parse_skill_frontmatter
from .workflows import load_workflow_catalog, validate_workflow_catalog
from .verify import verify_install
from .trace import write_trace
from .wizard import run_wizard
from .versioning import (
    VERSION_SYNC_PREFIX,
    check_version_files,
    commit_version_sync,
    plan_version,
    print_json,
    publish_preflight,
    push_lines_to_plans,
    stage_version_files,
    sync_version_files,
)


def _repo_root() -> Path:
    return Path(str(files("_localsetup"))).resolve().parent


def _localsetup_home(home: Path) -> Path:
    return home / ".local" / "share" / "localsetup"


def _config_data_root(config: InstallConfig, home: Path) -> Path:
    if config.data_root:
        return Path(config.data_root).expanduser().resolve()
    return _localsetup_home(home)


def _split_csv(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    expanded: list[str] = []
    for value in values:
        parts = [part.strip() for part in value.split(",")]
        if any(not part for part in parts):
            raise ValueError(f"empty value in comma-separated list: {value!r}")
        expanded.extend(parts)
    if not expanded:
        raise ValueError("at least one value is required")
    return expanded


def _add_config_flags(parser: argparse.ArgumentParser, *, include_apply: bool = False) -> None:
    parser.add_argument("--config")
    parser.add_argument("--target-directory", default=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", default=None, help="Emit JSON output explicitly; JSON is the default for non-Markdown commands.")
    parser.add_argument("--report")
    parser.add_argument("--backup-dir")
    parser.add_argument("--trace-json")
    parser.add_argument("--policy-mode", choices=["permissive", "standard", "strict", "ci"], default="standard")
    parser.add_argument("--dependency-mode", choices=sorted(DEPENDENCY_MODES))
    if include_apply:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--yes", action="store_true", dest="apply", help=argparse.SUPPRESS)


def _add_selector_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preset", choices=sorted(PRESETS))
    parser.add_argument("--packs", nargs="*")
    parser.add_argument("--skills", nargs="*")
    parser.add_argument("--skill-classes", nargs="*", dest="skill_classes")
    parser.add_argument("--skill-tags", nargs="*", dest="skill_tags")
    parser.add_argument("--exclude-skills", nargs="*", dest="exclude_skills")
    parser.add_argument("--workflows", nargs="*")
    parser.add_argument("--global-preset", choices=sorted(PRESETS), dest="global_preset")
    parser.add_argument("--global-packs", nargs="*", dest="global_packs")
    parser.add_argument("--global-skills", nargs="*", dest="global_skills")
    parser.add_argument("--global-skill-classes", nargs="*", dest="global_skill_classes")
    parser.add_argument("--global-skill-tags", nargs="*", dest="global_skill_tags")
    parser.add_argument("--global-exclude-skills", nargs="*", dest="global_exclude_skills")
    parser.add_argument("--global-workflows", nargs="*", dest="global_workflows")
    parser.add_argument("--repo-preset", choices=sorted(PRESETS), dest="repo_preset")
    parser.add_argument("--repo-packs", nargs="*", dest="repo_packs")
    parser.add_argument("--repo-skills", nargs="*", dest="repo_skills")
    parser.add_argument("--repo-skill-classes", nargs="*", dest="repo_skill_classes")
    parser.add_argument("--repo-skill-tags", nargs="*", dest="repo_skill_tags")
    parser.add_argument("--repo-exclude-skills", nargs="*", dest="repo_exclude_skills")
    parser.add_argument("--repo-workflows", nargs="*", dest="repo_workflows")
    parser.add_argument("--mode", choices=["symlink", "portable"])
    parser.add_argument("--platforms", "--tools", nargs="*", dest="platforms")


def _add_visual_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--color", choices=["auto", "always", "never"], default="auto")
    parser.add_argument("--no-color", action="store_const", const="never", dest="color")
    parser.add_argument("--glyphs", choices=["auto", "ascii", "unicode"], default="auto")


def _is_global_shim_invocation() -> bool:
    return os.environ.get(SHIM_ENV) == "1"


def _has_target_directory(args: argparse.Namespace) -> bool:
    return hasattr(args, "target_directory")


def _target_directory_value(args: argparse.Namespace) -> str | None:
    return getattr(args, "target_directory", None) if _has_target_directory(args) else None


def _inject_global_target(args: argparse.Namespace) -> None:
    if not _is_global_shim_invocation():
        return
    if args.cmd not in {"plan", "install", "update", "verify", "rollback", "adapters", "doctor", "migrate", "context", "convert", "harness", "context-index", "provenance", "health"}:
        return
    if _target_directory_value(args):
        return
    setattr(args, "target_directory", str(detect_invocation_target()))
    setattr(args, "detected_target_directory", True)


def _resolved_config(args: argparse.Namespace, default_home: Path) -> InstallConfig:
    base = load_install_config(Path(args.config).resolve() if getattr(args, "config", None) else None)
    cli_home = str(default_home)
    if getattr(args, "home_override", None):
        cli_home = args.home_override
    elif getattr(args, "home", None) is None and base.home:
        cli_home = base.home
    return merge_cli_config(
        base,
        platforms=_split_csv(getattr(args, "platforms", None)) if hasattr(args, "platforms") else None,
        packs=_split_csv(getattr(args, "packs", None)) if hasattr(args, "packs") else None,
        preset=getattr(args, "preset", None),
        skills=_split_csv(getattr(args, "skills", None)) if hasattr(args, "skills") else None,
        skill_classes=_split_csv(getattr(args, "skill_classes", None)) if hasattr(args, "skill_classes") else None,
        skill_tags=_split_csv(getattr(args, "skill_tags", None)) if hasattr(args, "skill_tags") else None,
        exclude_skills=_split_csv(getattr(args, "exclude_skills", None)) if hasattr(args, "exclude_skills") else None,
        workflows=_split_csv(getattr(args, "workflows", None)) if hasattr(args, "workflows") else None,
        global_packs=_split_csv(getattr(args, "global_packs", None)) if hasattr(args, "global_packs") else None,
        global_preset=getattr(args, "global_preset", None),
        global_skills=_split_csv(getattr(args, "global_skills", None)) if hasattr(args, "global_skills") else None,
        global_skill_classes=_split_csv(getattr(args, "global_skill_classes", None)) if hasattr(args, "global_skill_classes") else None,
        global_skill_tags=_split_csv(getattr(args, "global_skill_tags", None)) if hasattr(args, "global_skill_tags") else None,
        global_exclude_skills=_split_csv(getattr(args, "global_exclude_skills", None)) if hasattr(args, "global_exclude_skills") else None,
        global_workflows=_split_csv(getattr(args, "global_workflows", None)) if hasattr(args, "global_workflows") else None,
        repo_packs=_split_csv(getattr(args, "repo_packs", None)) if hasattr(args, "repo_packs") else None,
        repo_preset=getattr(args, "repo_preset", None),
        repo_skills=_split_csv(getattr(args, "repo_skills", None)) if hasattr(args, "repo_skills") else None,
        repo_skill_classes=_split_csv(getattr(args, "repo_skill_classes", None)) if hasattr(args, "repo_skill_classes") else None,
        repo_skill_tags=_split_csv(getattr(args, "repo_skill_tags", None)) if hasattr(args, "repo_skill_tags") else None,
        repo_exclude_skills=_split_csv(getattr(args, "repo_exclude_skills", None)) if hasattr(args, "repo_exclude_skills") else None,
        repo_workflows=_split_csv(getattr(args, "repo_workflows", None)) if hasattr(args, "repo_workflows") else None,
        attach_mode=getattr(args, "mode", None),
        home=cli_home,
        target_directory=getattr(args, "target_directory", None),
        dependency_mode=getattr(args, "dependency_mode", None),
        backup_dir=getattr(args, "backup_dir", None),
        report=getattr(args, "report", None),
        json_output=getattr(args, "json", None),
        markdown=getattr(args, "markdown", None),
    )


def _write_report(path: str | None, payload: dict, *, markdown: bool = False) -> None:
    if not path:
        return
    report_path = Path(path).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if markdown:
        save_text(report_path, render_markdown_report(payload))
    else:
        save_json(report_path, payload)


def _print_payload(payload: dict, *, markdown: bool = False) -> None:
    if markdown:
        print(render_markdown_report(payload), end="")
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))


def _print_no_command_help() -> None:
    print("localsetup: command required", file=sys.stderr)
    print("", file=sys.stderr)
    print("Examples:", file=sys.stderr)
    print("  localsetup doctor", file=sys.stderr)
    print("  localsetup verify --level filesystem", file=sys.stderr)
    print("  localsetup self-refresh --dependency-mode uv-sync", file=sys.stderr)
    print("  localsetup --help", file=sys.stderr)


def _health_status_from_payload(payload: dict) -> str:
    if payload.get("ok") is False or payload.get("blockers") or payload.get("decisions"):
        return "blocked"
    return "ok"


def _record_health_for_payload(
    *,
    root: Path,
    home: Path,
    target_root: Path,
    operation: str,
    mode: str,
    payload: dict,
    git_pre: dict | None = None,
    git_post: dict | None = None,
    planned_paths: list[str] | None = None,
) -> dict:
    blockers = [str(item) for item in payload.get("blockers", [])]
    warnings = [str(item) for item in payload.get("warnings", [])]
    delta = status_delta(git_pre, git_post, planned_paths or []) if git_pre and git_post else None
    install_payload = payload.get("install") if isinstance(payload.get("install"), dict) else {}
    event = write_health_event(
        repo_root=root,
        home=home,
        target_root=target_root,
        operation=operation,
        mode=mode,
        status=_health_status_from_payload(payload),
        payload=payload,
        blockers=blockers,
        warnings=warnings,
        decisions=payload.get("decisions", []),
        backups=payload.get("backups", []),
        journal_path=payload.get("journal") or install_payload.get("journal"),
        report_path=payload.get("report"),
        git_pre=git_pre,
        git_post=git_post,
        localsetup_created_delta=delta,
    )
    summary = {
        "event_id": event["event_id"],
        "status": event["status"],
        "latest": str(home / ".local" / "share" / "localsetup" / "state" / "health" / "latest.json"),
        "repo_summary": str(target_root / ".localsetup" / "health.json"),
        "agent_status": str(target_root / ".localsetup" / "AGENT_STATUS.md"),
        "next_actions": event.get("next_actions", []),
    }
    payload["health"] = summary
    return summary


def _all_configured_packs(repo_root: Path) -> list[str]:
    pack = load_pack_config(repo_root)
    return list(pack.packs.keys())


def _policy_findings(root: Path, skill_names: list[str], mode: str) -> dict:
    by_name = {skill.name: skill for skill in load_skill_catalog(root)}
    warnings: list[str] = []
    blockers: list[str] = []
    for skill_name in skill_names:
        skill = by_name.get(skill_name)
        if not skill:
            continue
        frontmatter = parse_skill_frontmatter(skill.path / "SKILL.md")
        risk = str(frontmatter.get("risk", "low"))
        permissions = frontmatter.get("permissions", [])
        invalid_metadata = False
        if risk not in {"low", "medium", "high"}:
            invalid_metadata = True
            warnings.append(f"{skill_name}: invalid risk metadata: {risk}")
        if not isinstance(permissions, list) or not all(isinstance(item, str) for item in permissions):
            invalid_metadata = True
            warnings.append(f"{skill_name}: invalid permissions metadata")
            permissions = []
        if risk in {"medium", "high"} or permissions:
            warnings.append(f"{skill_name}: risk={risk}; permissions={permissions}")
        if mode in {"strict", "ci"} and invalid_metadata:
            blockers.append(f"invalid skill policy metadata blocked by {mode} policy: {skill_name}")
        if mode in {"strict", "ci"} and risk == "high":
            blockers.append(f"high-risk skill blocked by {mode} policy: {skill_name}")
    return {"mode": mode, "warnings": warnings, "blockers": blockers}


def _add_harness_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-directory", default=argparse.SUPPRESS)


def _harness_target(args: argparse.Namespace) -> Path | None:
    value = getattr(args, "target_directory", None)
    return Path(value).expanduser().resolve() if value else None


def _existing_target_platforms(repo_root: Path, target_root: Path, home: Path) -> list[dict[str, str]]:
    global_root = expand_user_path(load_pack_config(repo_root).global_root, home)
    selected: list[dict[str, str]] = []
    for platform in load_platforms(repo_root):
        for rel in platform.repo_paths:
            candidate = target_root / rel
            state = adapter_path_state(candidate, global_root)
            if state["points_to_global"] or state["is_portable_copy"]:
                selected.append(
                    {
                        "platform": platform.platform_id,
                        "mode": "portable" if state["is_portable_copy"] else "symlink",
                    }
                )
                break
    return sorted(selected, key=lambda item: item["platform"])


_SELECTOR_CONFIG_FIELDS = (
    "platforms",
    "packs",
    "preset",
    "skills",
    "skill_classes",
    "skill_tags",
    "exclude_skills",
    "workflows",
    "global_packs",
    "global_preset",
    "global_skills",
    "global_skill_classes",
    "global_skill_tags",
    "global_exclude_skills",
    "global_workflows",
    "repo_packs",
    "repo_preset",
    "repo_skills",
    "repo_skill_classes",
    "repo_skill_tags",
    "repo_exclude_skills",
    "repo_workflows",
)


def _selector_free(config: InstallConfig) -> bool:
    return all(getattr(config, field_name) is None for field_name in _SELECTOR_CONFIG_FIELDS)


def _repair_detected_existing_state(repair: dict) -> bool:
    shape = repair.get("detected_shape", {})
    if any(
        shape.get(key)
        for key in (
            "modern_lockfile",
            "legacy_lockfile",
            "adapter_paths",
            "historical_adapter_paths",
            "stale_localsetup",
            "partial_adapters",
            "protected_source_root",
        )
    ):
        return True
    inferred = repair.get("inferred", {})
    return bool(inferred.get("platforms"))


def _global_selector_kwargs_from_lock(target_root: Path) -> dict:
    lock = load_json(target_root / ".localsetup" / "lock.json")
    selectors = lock.get("global_baseline_selectors") if isinstance(lock, dict) else {}
    if not isinstance(selectors, dict):
        selectors = {}
    kwargs = {
        "global_packs": selectors.get("packs") if isinstance(selectors.get("packs"), list) else None,
        "global_preset": selectors.get("preset") if isinstance(selectors.get("preset"), str) else None,
        "global_skills": selectors.get("skills") if isinstance(selectors.get("skills"), list) else None,
        "global_workflows": selectors.get("workflows") if isinstance(selectors.get("workflows"), list) else None,
        "global_skill_classes": selectors.get("skill_classes") if isinstance(selectors.get("skill_classes"), list) else None,
        "global_skill_tags": selectors.get("skill_tags") if isinstance(selectors.get("skill_tags"), list) else None,
        "global_exclude_skills": selectors.get("exclude_skills") if isinstance(selectors.get("exclude_skills"), list) else None,
    }
    if any(value is not None for value in kwargs.values()):
        return kwargs
    if isinstance(lock.get("global_baseline_workflows"), list):
        return {
            "global_preset": "custom",
            "global_workflows": lock["global_baseline_workflows"],
            "global_skills": lock.get("global_baseline_skills") if isinstance(lock.get("global_baseline_skills"), list) else None,
        }
    if isinstance(lock.get("global_baseline_packs"), list):
        return {"global_packs": lock["global_baseline_packs"], "global_preset": "custom"}
    return {"global_preset": "core"}


def _build_auto_inferred_plan(root: Path, home: Path, target_root: Path, repair: dict):
    inferred = repair.get("inferred", {})
    return build_install_plan(
        root,
        home=home,
        **_global_selector_kwargs_from_lock(target_root),
        repo_preset="custom",
        repo_skills=list(inferred.get("repo_skills") or inferred.get("repo_packages") or []),
        repo_workflows=list(inferred.get("repo_workflows") or []),
        attach_mode=str(inferred.get("attach_mode") or "symlink"),
        platform_ids=list(inferred.get("platforms") or []),
        target_root=target_root,
    )


def _build_auto_new_repo_plan(root: Path, home: Path, target_root: Path):
    return build_install_plan(
        root,
        home=home,
        global_preset="suggested",
        platform_ids=[],
        target_root=target_root,
    )


def _auto_plan_payload(
    root: Path,
    home: Path,
    config: InstallConfig,
    target_root: Path,
    plan,
    policy: dict,
    *,
    mode: str,
    repair: dict,
) -> dict:
    return {
        "auto_mode": mode,
        "actions": [{"kind": a.kind, "path": str(a.path), "details": a.details} for a in plan.actions],
        "config": config_to_dict(config),
        "attachment": {
            "target_root": str(target_root),
            "platforms": plan.rollback_metadata.get("platforms", []),
            "global_only": plan.rollback_metadata.get("global_only", False),
        },
        "inventory": install_inventory(root, home=home, target_root=target_root, platform_ids=plan.rollback_metadata.get("platforms", [])),
        "warnings": [],
        "policy": policy,
        "rollback": plan.rollback_metadata,
        "repair": repair,
    }


def _apply_install_plan(
    root: Path,
    home: Path,
    config: InstallConfig,
    target_root: Path,
    plan,
    policy: dict,
    *,
    mode: str | None = None,
) -> tuple[dict, int]:
    git_pre = git_status_snapshot(target_root)
    adapter_plan_paths: list[str] = []
    for action in plan.actions:
        if action.kind != "attach_repo_path":
            continue
        try:
            adapter_plan_paths.append(str(action.path.relative_to(target_root)))
        except ValueError:
            continue
    planned_paths = [
        ".localsetup/lock.json",
        ".localsetup/health.json",
        ".localsetup/AGENT_STATUS.md",
        *adapter_plan_paths,
    ]
    if policy["blockers"]:
        payload = {"ok": False, "policy": policy, "blockers": policy["blockers"]}
        if mode:
            payload["auto_mode"] = mode
        git_post = git_status_snapshot(target_root)
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=target_root,
            operation="install",
            mode=mode or "explicit",
            payload=payload,
            git_pre=git_pre,
            git_post=git_post,
            planned_paths=planned_paths,
        )
        return payload, 1
    dependency_info = (
        ensure_dependencies(root, mode=config.dependency_mode, data_root=_config_data_root(config, home), target_root=target_root)
        if config.dependency_mode != "prompt-only"
        else None
    )
    try:
        result = apply_plan(root, plan, home=home, dry_run=False, dependency_info=dependency_info, target_root=target_root)
    except PackageRootLockTimeout as exc:
        payload = {"ok": False, "status_code": exc.status_code, "blockers": [str(exc)]}
        if mode:
            payload["auto_mode"] = mode
        git_post = git_status_snapshot(target_root)
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=target_root,
            operation="install",
            mode=mode or "explicit",
            payload=payload,
            git_pre=git_pre,
            git_post=git_post,
            planned_paths=planned_paths,
        )
        return payload, 1
    if dependency_info:
        result["dependencies"] = dependency_info
    result["attachment"] = {
        "target_root": str(target_root),
        "platforms": plan.rollback_metadata.get("platforms", []),
        "global_only": plan.rollback_metadata.get("global_only", False),
    }
    if policy["warnings"]:
        result.setdefault("warnings", []).extend(policy["warnings"])
    result["policy"] = policy
    if mode:
        result["auto_mode"] = mode
    result["ok"] = True
    git_post = git_status_snapshot(target_root)
    _record_health_for_payload(
        root=root,
        home=home,
        target_root=target_root,
        operation="install",
        mode=mode or "explicit",
        payload=result,
        git_pre=git_pre,
        git_post=git_post,
        planned_paths=planned_paths,
    )
    return result, 0


def _auto_default_context(root: Path, home: Path, config: InstallConfig, target_root: Path) -> dict:
    repair = run_repair(
        root,
        home=home,
        target_root=target_root,
        platform_ids=None,
        backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
        dependency_mode=config.dependency_mode,
        apply=False,
    )
    if repair.get("blockers") or repair.get("decisions"):
        return {"mode": "repair_required", "repair": repair, "plan": None}
    if not _repair_detected_existing_state(repair):
        return {"mode": "default_new_repo", "repair": repair, "plan": _build_auto_new_repo_plan(root, home, target_root)}
    if repair.get("actions"):
        return {"mode": "repair_required", "repair": repair, "plan": None}
    return {"mode": "inferred_existing", "repair": repair, "plan": _build_auto_inferred_plan(root, home, target_root, repair)}


def _run_self_refresh(
    root: Path,
    config: InstallConfig,
    home: Path,
    *,
    packs_override: list[str] | None = None,
    platforms_override: list[str] | None = None,
    attach_mode_explicit: bool = False,
) -> dict:
    target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else root
    packs = packs_override if packs_override is not None else _all_configured_packs(root)
    existing_platforms = _existing_target_platforms(root, target_root, home)
    platforms = platforms_override if platforms_override is not None else [item["platform"] for item in existing_platforms]
    attach_mode = config.attach_mode
    if not attach_mode_explicit:
        selected_modes = {item["mode"] for item in existing_platforms if item["platform"] in set(platforms)}
        if len(selected_modes) == 1:
            attach_mode = selected_modes.pop()
        elif len(selected_modes) > 1:
            return {
                "ok": False,
                "issues": [
                    "self-refresh found mixed existing adapter modes; pass --mode symlink or --mode portable explicitly"
                ],
                "selected": {
                    "packs": packs,
                    "platforms": platforms,
                    "target_root": str(target_root),
                    "attach_mode": None,
                },
            }
    dependency_info = (
        ensure_dependencies(root, mode=config.dependency_mode, data_root=_config_data_root(config, home), target_root=target_root)
        if config.dependency_mode != "prompt-only"
        else None
    )
    plan = build_install_plan(
        root,
        home=home,
        packs=packs,
        preset=config.preset,
        skills=config.skills,
        workflows=config.workflows,
        skill_classes=config.skill_classes,
        skill_tags=config.skill_tags,
        exclude_skills=config.exclude_skills,
        global_packs=config.global_packs,
        global_preset=config.global_preset,
        global_skills=config.global_skills,
        global_workflows=config.global_workflows,
        global_skill_classes=config.global_skill_classes,
        global_skill_tags=config.global_skill_tags,
        global_exclude_skills=config.global_exclude_skills,
        repo_packs=config.repo_packs,
        repo_preset=config.repo_preset,
        repo_skills=config.repo_skills,
        repo_workflows=config.repo_workflows,
        repo_skill_classes=config.repo_skill_classes,
        repo_skill_tags=config.repo_skill_tags,
        repo_exclude_skills=config.repo_exclude_skills,
        attach_mode=attach_mode,
        platform_ids=platforms,
        target_root=target_root,
    )
    result = apply_plan(root, plan, home=home, dry_run=False, dependency_info=dependency_info, target_root=target_root)
    verify = verify_install(root, home=home, platform_ids=platforms, target_root=target_root)
    if dependency_info:
        result["dependencies"] = dependency_info
    return {
        "ok": verify["ok"],
        "selected": {
            "packs": packs,
            "platforms": platforms,
            "target_root": str(target_root),
            "attach_mode": attach_mode,
        },
        "apply": result,
        "verify": verify,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localsetup")
    parser.add_argument("--home")
    parser.add_argument("--source-root")
    parser.add_argument("--repo", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target-directory")
    sub = parser.add_subparsers(dest="cmd")

    plan_p = sub.add_parser("plan")
    _add_config_flags(plan_p)
    _add_selector_flags(plan_p)

    install_p = sub.add_parser("install")
    _add_config_flags(install_p, include_apply=True)
    _add_selector_flags(install_p)

    verify_p = sub.add_parser("verify")
    _add_config_flags(verify_p)
    verify_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    verify_p.add_argument("--level", choices=["filesystem"], default="filesystem")

    rollback_p = sub.add_parser("rollback")
    _add_config_flags(rollback_p)
    rollback_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")

    update_p = sub.add_parser("update")
    _add_config_flags(update_p)
    _add_selector_flags(update_p)

    adapters_p = sub.add_parser("adapters")
    adapters_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    adapters_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    adapters_p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    adapters_p.add_argument("--provenance", action="store_true")
    configure_p = sub.add_parser("configure")
    _add_config_flags(configure_p)
    _add_selector_flags(configure_p)
    configure_p.add_argument("--home-override")

    doctor_p = sub.add_parser("doctor")
    _add_config_flags(doctor_p)
    _add_selector_flags(doctor_p)
    doctor_p.add_argument("--provenance", action="store_true")
    doctor_sub = doctor_p.add_subparsers(dest="doctor_action")
    doctor_repair_p = doctor_sub.add_parser("repair")
    _add_config_flags(doctor_repair_p)
    doctor_repair_p.add_argument("--yes", action="store_true", dest="apply")
    doctor_repair_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    doctor_repair_p.add_argument(
        "--repair-mode",
        choices=["report-only", "safe-repair", "migration-plan", "apply-with-backups"],
        default=None,
    )
    doctor_repair_p.add_argument("--allow", action="append", default=[])
    doctor_repair_p.add_argument("--agent-prompt", action="store_true")
    doctor_repair_p.add_argument("--emit-agent-prompt")

    migrate_p = sub.add_parser("migrate")
    _add_config_flags(migrate_p)
    migrate_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    migrate_p.add_argument("--dry-run", action="store_true")

    context_p = sub.add_parser("context")
    _add_config_flags(context_p)
    _add_selector_flags(context_p)
    context_p.add_argument("--markdown", action="store_true", default=None)

    convert_p = sub.add_parser("convert")
    _add_config_flags(convert_p, include_apply=True)
    _add_selector_flags(convert_p)

    sub.add_parser("catalog")
    diff_p = sub.add_parser("diff")
    _add_config_flags(diff_p)
    _add_selector_flags(diff_p)
    skill_p = sub.add_parser("skill")
    skill_sub = skill_p.add_subparsers(dest="skill_action", required=True)
    skill_search = skill_sub.add_parser("search")
    skill_search.add_argument("query", nargs="?")
    skill_info = skill_sub.add_parser("info")
    skill_info.add_argument("query")
    workflow_p = sub.add_parser("workflow")
    workflow_sub = workflow_p.add_subparsers(dest="workflow_action", required=True)
    workflow_search = workflow_sub.add_parser("search")
    workflow_search.add_argument("query", nargs="?")
    workflow_info = workflow_sub.add_parser("info")
    workflow_info.add_argument("query")
    why_p = sub.add_parser("why")
    why_p.add_argument("--packs", nargs="*")
    sub.add_parser("graph")
    adopt_p = sub.add_parser("adopt")
    adopt_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    detach_p = sub.add_parser("detach")
    _add_config_flags(detach_p)
    detach_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms", required=True)
    sbom_p = sub.add_parser("sbom")
    sbom_p.add_argument("--format", choices=["cyclonedx"], default="cyclonedx")
    sbom_p.add_argument("--out", required=True)
    sbom_p.add_argument("--installed", action="store_true")
    sbom_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    scan_migration_p = sub.add_parser("scan-migration")
    scan_migration_p.add_argument("--include-expected", action="store_true")
    audit_global_p = sub.add_parser("audit-global-first")
    audit_global_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    sub.add_parser("validate-catalog")
    sub.add_parser("generate-docs")
    provenance_p = sub.add_parser("provenance")
    provenance_sub = provenance_p.add_subparsers(dest="provenance_action", required=True)
    provenance_report_p = provenance_sub.add_parser("report")
    _add_config_flags(provenance_report_p)
    provenance_report_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    repair_p = provenance_sub.add_parser("repair")
    repair_p.add_argument("--plan", action="store_true", required=True)
    health_p = sub.add_parser("health")
    health_p.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    health_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    health_sub = health_p.add_subparsers(dest="health_action")
    health_queue = health_sub.add_parser("repair-queue")
    health_queue.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    health_queue.add_argument("--agent-prompts")
    harness_p = sub.add_parser("harness")
    harness_sub = harness_p.add_subparsers(dest="harness_topic", required=True)
    heartbeat_p = harness_sub.add_parser("codex-heartbeat")
    heartbeat_sub = heartbeat_p.add_subparsers(dest="harness_action", required=True)
    for action_name in ("plan", "init", "status"):
        action_p = heartbeat_sub.add_parser(action_name)
        _add_harness_target_flags(action_p)
    for action_name in ("enable", "disable"):
        action_p = heartbeat_sub.add_parser(action_name)
        _add_harness_target_flags(action_p)
        action_p.add_argument("--install-crontab", action="store_true")
        action_p.add_argument("--yes", action="store_true")
    run_p = heartbeat_sub.add_parser("run")
    _add_harness_target_flags(run_p)
    run_p.add_argument("--no-agent", action="store_true")
    run_p.add_argument("--force", action="store_true")
    finalizer_p = harness_sub.add_parser("repo-finalizer")
    finalizer_sub = finalizer_p.add_subparsers(dest="harness_action", required=True)
    for action_name in ("plan", "status"):
        action_p = finalizer_sub.add_parser(action_name)
        _add_harness_target_flags(action_p)
        action_p.add_argument("--mode", choices=["source", "target"])
        action_p.add_argument("--json", action="store_true")
    finalizer_run_p = finalizer_sub.add_parser("run")
    _add_harness_target_flags(finalizer_run_p)
    finalizer_run_p.add_argument("--mode", choices=["source", "target"])
    finalizer_run_p.add_argument("--json", action="store_true")
    finalizer_run_p.add_argument("--no-commit", action="store_true")
    finalizer_run_p.add_argument("--checkpoint", action="store_true")
    finalizer_run_p.add_argument("--message")
    docs_align_p = sub.add_parser("docs-align")
    docs_align_p.add_argument("docs_align_args", nargs=argparse.REMAINDER)

    plugin_p = sub.add_parser("plugin")
    plugin_sub = plugin_p.add_subparsers(dest="plugin_action", required=True)
    plugin_list_p = plugin_sub.add_parser("list")
    plugin_list_p.add_argument("--platform", choices=["codex"], default="codex")
    plugin_plan_p = plugin_sub.add_parser("plan")
    plugin_plan_p.add_argument("--platform", choices=["codex"], default="codex")
    plugin_plan_p.add_argument("--plugin-packs", nargs="*")
    plugin_plan_p.add_argument("--output")
    plugin_build_p = plugin_sub.add_parser("build")
    plugin_build_p.add_argument("--platform", choices=["codex"], default="codex")
    plugin_build_p.add_argument("--plugin-packs", nargs="*")
    plugin_build_p.add_argument("--output", required=True)
    plugin_validate_p = plugin_sub.add_parser("validate")
    plugin_validate_p.add_argument("--platform", choices=["codex"], default="codex")
    plugin_validate_p.add_argument("--path", required=True)

    context_index_p = sub.add_parser("context-index")
    context_index_p.add_argument("context_index_args", nargs=argparse.REMAINDER)

    hook_p = sub.add_parser("hook-gate")
    hook_p.add_argument("--out", default="/tmp/localsetup-public.tar.gz")
    hook_p.add_argument("--runner")

    version_plan_p = sub.add_parser("version-plan")
    version_plan_p.add_argument("--base")
    version_plan_p.add_argument("--head")
    version_plan_p.add_argument("--ref")
    version_plan_p.add_argument("--push-stdin", action="store_true")

    version_sync_p = sub.add_parser("version-sync")
    version_sync_p.add_argument("--base")
    version_sync_p.add_argument("--head")
    version_sync_p.add_argument("--target")
    version_sync_p.add_argument("--check", action="store_true")
    version_sync_p.add_argument("--stage", action="store_true")
    version_sync_p.add_argument("--commit", action="store_true")

    publish_preflight_p = sub.add_parser("publish-preflight")
    publish_preflight_p.add_argument("--base")
    publish_preflight_p.add_argument("--head")
    publish_preflight_p.add_argument("--fix", action="store_true")

    release_push_p = sub.add_parser("release-push")
    release_push_p.add_argument("push_args", nargs=argparse.REMAINDER)
    self_refresh_p = sub.add_parser("self-refresh")
    _add_config_flags(self_refresh_p)
    _add_selector_flags(self_refresh_p)

    sub.add_parser("install-hooks")
    sub.add_parser("register-shell")

    wizard_p = sub.add_parser("wizard")
    _add_config_flags(wizard_p)
    _add_selector_flags(wizard_p)
    wizard_p.add_argument("--caller-directory")
    wizard_p.add_argument("--no-register-shell", action="store_true")
    wizard_p.add_argument("--target-directory-origin", choices=["explicit", "inferred"], default="explicit")
    _add_visual_flags(wizard_p)

    package_p = sub.add_parser("package")
    package_p.add_argument("--out", default="dist/localsetup-public.tar.gz")
    verify_release_p = sub.add_parser("verify-release")
    verify_release_p.add_argument("artifact")
    verify_release_p.add_argument("--sha256")
    verify_release_p.add_argument("--sbom")
    verify_release_p.add_argument("--expected-commit")
    verify_release_p.add_argument("--expected-tag")

    args = parser.parse_args(argv)
    if args.cmd is None:
        _print_no_command_help()
        return 2
    _inject_global_target(args)
    root = Path(args.source_root or args.repo or str(_repo_root())).resolve()
    home = Path(args.home or Path.home()).expanduser().resolve()

    if args.cmd in {"plan", "install", "update"}:
        started_at = time.time()
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        auto_context = (
            _auto_default_context(root, home, config, attachment_root)
            if _selector_free(config) and config.target_directory
            else None
        )
        if auto_context is not None:
            mode = str(auto_context["mode"])
            repair = auto_context["repair"]
            plan = auto_context["plan"]
            if plan is not None:
                policy = _policy_findings(root, plan.rollback_metadata.get("skills", []), getattr(args, "policy_mode", "standard"))
                if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
                    payload = _auto_plan_payload(root, home, config, attachment_root, plan, policy, mode=mode, repair=repair)
                    _write_report(config.output.report, payload)
                    _print_payload(payload)
                    write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok", attributes={"dry_run": True, "auto_mode": mode}, started_at=started_at)
                    return 0
                result, status = _apply_install_plan(root, home, config, attachment_root, plan, policy, mode=mode)
                result["repair"] = repair
                _write_report(config.output.report, result)
                _print_payload(result)
                write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok" if status == 0 else "failed", attributes={"target_root": str(attachment_root), "auto_mode": mode}, started_at=started_at)
                return status

            if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
                payload = {
                    "auto_mode": mode,
                    "ok": bool(repair.get("ok")),
                    "config": config_to_dict(config),
                    "attachment": {
                        "target_root": str(attachment_root),
                        "platforms": repair.get("inferred", {}).get("platforms", []),
                        "global_only": not bool(repair.get("inferred", {}).get("platforms", [])),
                    },
                    "repair": repair,
                    "actions": repair.get("actions", []),
                    "warnings": repair.get("warnings", []),
                    "decisions": repair.get("decisions", []),
                    "blockers": repair.get("blockers", []),
                }
                _write_report(config.output.report, payload)
                _print_payload(payload)
                write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok" if payload["ok"] else "failed", attributes={"dry_run": True, "auto_mode": mode}, started_at=started_at)
                return 0

            applied = run_repair(
                root,
                home=home,
                target_root=attachment_root,
                platform_ids=None,
                backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
                dependency_mode=config.dependency_mode,
                apply=True,
            )
            applied["auto_mode"] = mode
            _write_report(config.output.report, applied)
            _print_payload(applied)
            write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok" if applied["ok"] else "failed", attributes={"target_root": str(attachment_root), "auto_mode": mode, "applied": bool(applied.get("applied"))}, started_at=started_at)
            return 0 if applied["ok"] else 1

        plan = build_install_plan(
            root,
            home=home,
            packs=config.packs,
            preset=config.preset,
            skills=config.skills,
            workflows=config.workflows,
            skill_classes=config.skill_classes,
            skill_tags=config.skill_tags,
            exclude_skills=config.exclude_skills,
            global_packs=config.global_packs,
            global_preset=config.global_preset,
            global_skills=config.global_skills,
            global_workflows=config.global_workflows,
            global_skill_classes=config.global_skill_classes,
            global_skill_tags=config.global_skill_tags,
            global_exclude_skills=config.global_exclude_skills,
            repo_packs=config.repo_packs,
            repo_preset=config.repo_preset,
            repo_skills=config.repo_skills,
            repo_workflows=config.repo_workflows,
            repo_skill_classes=config.repo_skill_classes,
            repo_skill_tags=config.repo_skill_tags,
            repo_exclude_skills=config.repo_exclude_skills,
            attach_mode=config.attach_mode,
            platform_ids=config.platforms,
            target_root=target_root,
        )
        policy = _policy_findings(root, plan.rollback_metadata.get("skills", []), getattr(args, "policy_mode", "standard"))
        detected_target = bool(getattr(args, "detected_target_directory", False))
        if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
            warnings = []
            if config.target_directory and not config.platforms and not detected_target:
                warnings.append("target directory was provided but no platforms were selected; plan is global-only with no repo adapters")
            payload = {
                "auto_mode": "explicit",
                "actions": [{"kind": a.kind, "path": str(a.path), "details": a.details} for a in plan.actions],
                "config": config_to_dict(config),
                "attachment": {
                    "target_root": str(attachment_root),
                    "platforms": plan.rollback_metadata.get("platforms", []),
                    "global_only": plan.rollback_metadata.get("global_only", False),
                },
                "inventory": install_inventory(root, home=home, target_root=target_root, platform_ids=config.platforms),
                "warnings": warnings,
                "policy": policy,
                "rollback": plan.rollback_metadata,
            }
            _write_report(config.output.report, payload)
            _print_payload(payload)
            write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok", attributes={"dry_run": True}, started_at=started_at)
            return 0
        result, status = _apply_install_plan(root, home, config, attachment_root, plan, policy)
        result["auto_mode"] = "explicit"
        if config.target_directory and not config.platforms and not detected_target:
            result["warnings"] = ["target directory was provided but no platforms were selected; install was global-only with no repo adapters"]
        _write_report(config.output.report, result)
        _print_payload(result)
        write_trace(getattr(args, "trace_json", None), event=args.cmd, status="ok" if status == 0 else "failed", attributes={"target_root": str(attachment_root)}, started_at=started_at)
        return status

    if args.cmd == "wizard":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        caller_directory = Path(args.caller_directory).expanduser().resolve() if args.caller_directory else None
        return run_wizard(
            repo_root=root,
            home=home,
            caller_directory=caller_directory,
            target_directory=target_root,
            target_directory_is_explicit=bool(target_root and args.target_directory_origin == "explicit"),
            platforms=config.platforms,
            packs=config.packs,
            preset=config.preset,
            skills=config.skills,
            workflows=config.workflows,
            skill_classes=config.skill_classes,
            skill_tags=config.skill_tags,
            exclude_skills=config.exclude_skills,
            global_packs=config.global_packs,
            global_preset=config.global_preset,
            global_skills=config.global_skills,
            global_workflows=config.global_workflows,
            global_skill_classes=config.global_skill_classes,
            global_skill_tags=config.global_skill_tags,
            global_exclude_skills=config.global_exclude_skills,
            repo_packs=config.repo_packs,
            repo_preset=config.repo_preset,
            repo_skills=config.repo_skills,
            repo_workflows=config.repo_workflows,
            repo_skill_classes=config.repo_skill_classes,
            repo_skill_tags=config.repo_skill_tags,
            repo_exclude_skills=config.repo_exclude_skills,
            attach_mode=config.attach_mode,
            dependency_mode=config.dependency_mode,
            register_shell=not args.no_register_shell,
            color_mode=args.color,
            glyph_mode=args.glyphs,
        )

    if args.cmd == "verify":
        started_at = time.time()
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        git_pre = git_status_snapshot(attachment_root)
        payload = verify_install(root, home=home, platform_ids=config.platforms, target_root=target_root, level=args.level)
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=attachment_root,
            operation="verify",
            mode=args.level,
            payload=payload,
            git_pre=git_pre,
            git_post=git_status_snapshot(attachment_root),
            planned_paths=[".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        write_trace(getattr(args, "trace_json", None), event="verify", status="ok" if payload["ok"] else "failed", attributes={"level": args.level}, started_at=started_at)
        return 0 if payload["ok"] else 1

    if args.cmd == "rollback":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        payload = rollback(root, home=home, platform_ids=config.platforms, target_root=target_root)
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0

    if args.cmd == "adapters":
        pack = load_pack_config(root)
        target_root = Path(getattr(args, "target_directory", None)).expanduser().resolve() if getattr(args, "target_directory", None) else None
        global_root = expand_user_path(pack.global_root, home)
        payload = adapter_status(
            root,
            home,
            global_root,
            platform_ids=_split_csv(args.platforms),
            target_root=target_root,
        )
        if args.provenance:
            attachment_root = target_root or root
            registry_path = expand_user_path(pack.global_registry, home)
            lock = json.loads((attachment_root / ".localsetup" / "lock.json").read_text(encoding="utf-8")) if (attachment_root / ".localsetup" / "lock.json").exists() else {}
            provenance = provenance_report(
                root,
                lock=lock,
                registry=load_registry(registry_path) if registry_path.exists() else {},
                global_root=global_root,
                adapters=payload,
            )
            print(json.dumps({"adapters": payload, "provenance": provenance, "provenance_warnings": provenance["warnings"], "provenance_repair_hints": provenance["repair_hints"]}, indent=2, sort_keys=True))
            return 0
        print(
            json.dumps(
                payload,
                indent=2,
            )
        )
        return 0

    if args.cmd == "configure":
        config = _resolved_config(args, home)
        payload = config_to_dict(config)
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0

    if args.cmd == "doctor":
        started_at = time.time()
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        if getattr(args, "doctor_action", None) == "repair":
            attachment_root = target_root or root
            git_pre = git_status_snapshot(attachment_root)
            payload = run_repair(
                root,
                home=home,
                target_root=target_root,
                platform_ids=config.platforms,
                backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
                dependency_mode=config.dependency_mode,
                apply=bool(args.apply),
                repair_mode=getattr(args, "repair_mode", None) or ("safe-repair" if args.apply else "report-only"),
                allow=getattr(args, "allow", None) or [],
            )
            emit_prompt = getattr(args, "emit_agent_prompt", None)
            if getattr(args, "agent_prompt", False) or emit_prompt:
                prompt_path = Path(emit_prompt).expanduser().resolve() if emit_prompt else None
                payload["agent_prompt"] = agent_prompt_payload(payload, path=prompt_path)
            _record_health_for_payload(
                root=root,
                home=home,
                target_root=attachment_root,
                operation="doctor.repair",
                mode=payload.get("repair_mode", "report-only"),
                payload=payload,
                git_pre=git_pre,
                git_post=git_status_snapshot(attachment_root),
                planned_paths=[".localsetup/lock.json", ".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
            )
            _write_report(config.output.report, payload)
            _print_payload(payload)
            write_trace(
                getattr(args, "trace_json", None),
                event="doctor.repair",
                status="ok" if payload["ok"] else "failed",
                attributes={"target_root": str(target_root or root), "applied": bool(payload["applied"])},
                started_at=started_at,
            )
            return 0 if payload["ok"] else 1
        payload = run_doctor(
            root,
            home=home,
            packs=config.packs,
            platform_ids=config.platforms,
            dependency_mode=config.dependency_mode,
            data_root=_config_data_root(config, home),
            target_root=target_root,
        )
        payload["shell_registration"] = shell_registration_status(root, home=home)
        if payload["shell_registration"]["warnings"]:
            payload["warnings"].extend(payload["shell_registration"]["warnings"])
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=target_root or root,
            operation="doctor",
            mode="report-only",
            payload=payload,
            git_pre=git_status_snapshot(target_root or root),
            git_post=git_status_snapshot(target_root or root),
            planned_paths=[".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        write_trace(getattr(args, "trace_json", None), event="doctor", status="ok" if payload["ok"] else "failed", attributes={"target_root": str(target_root or root)}, started_at=started_at)
        return 0 if payload["ok"] else 1

    if args.cmd == "provenance":
        if args.provenance_action == "repair":
            payload = {
                "ok": True,
                "planned": True,
                "actions": [],
                "message": "provenance repair is intentionally report-only in this release",
            }
            _print_payload(payload)
            return 0
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        pack = load_pack_config(root)
        global_root = expand_user_path(pack.global_root, home)
        registry_path = expand_user_path(pack.global_registry, home)
        lock_path = attachment_root / ".localsetup" / "lock.json"
        lock = json.loads(lock_path.read_text(encoding="utf-8")) if lock_path.exists() else {}
        adapters = (
            adapter_status(root, home, global_root, platform_ids=config.platforms, target_root=target_root)
            if config.platforms is not None
            else recorded_adapter_status(lock, global_root)
        )
        payload = provenance_report(
            root,
            lock=lock,
            registry=load_registry(registry_path) if registry_path.exists() else {},
            global_root=global_root,
            adapters=adapters,
        )
        payload["adapters"] = adapters
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0

    if args.cmd == "health":
        target_root = Path(getattr(args, "target_directory", None)).expanduser().resolve() if getattr(args, "target_directory", None) else root
        if getattr(args, "health_action", None) == "repair-queue":
            output_dir = getattr(args, "agent_prompts", None)
            payload = (
                write_repair_queue_prompts(home=home, output_dir=Path(output_dir).expanduser().resolve())
                if output_dir
                else repair_queue(home=home)
            )
            _print_payload(payload)
            return 0
        _print_payload(read_health_status(home=home, target_root=target_root))
        return 0

    if args.cmd == "migrate":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        git_pre = git_status_snapshot(attachment_root)
        apply_migration = not args.dry_run and config.migration_mode != "report-only"
        payload = conservative_migrate(
            root,
            home=home,
            platform_ids=config.platforms,
            target_root=target_root,
            backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
            apply=apply_migration,
        )
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=attachment_root,
            operation="migrate",
            mode="apply" if apply_migration else "report-only",
            payload=payload,
            git_pre=git_pre,
            git_post=git_status_snapshot(attachment_root),
            planned_paths=[".localsetup/lock.json", ".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "convert":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        git_pre = git_status_snapshot(attachment_root)
        payload = convert_repo(
            root,
            home=home,
            packs=config.packs,
            preset=config.preset,
            skills=config.skills,
            workflows=config.workflows,
            skill_classes=config.skill_classes,
            skill_tags=config.skill_tags,
            exclude_skills=config.exclude_skills,
            global_packs=config.global_packs,
            global_preset=config.global_preset,
            global_skills=config.global_skills,
            global_workflows=config.global_workflows,
            global_skill_classes=config.global_skill_classes,
            global_skill_tags=config.global_skill_tags,
            global_exclude_skills=config.global_exclude_skills,
            repo_packs=config.repo_packs,
            repo_preset=config.repo_preset,
            repo_skills=config.repo_skills,
            repo_workflows=config.repo_workflows,
            repo_skill_classes=config.repo_skill_classes,
            repo_skill_tags=config.repo_skill_tags,
            repo_exclude_skills=config.repo_exclude_skills,
            platform_ids=config.platforms,
            attach_mode=config.attach_mode,
            target_root=target_root,
            backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
            dependency_mode=config.dependency_mode,
            apply=bool(args.apply),
        )
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=attachment_root,
            operation="convert",
            mode="apply" if args.apply else "report-only",
            payload=payload,
            git_pre=git_pre,
            git_post=git_status_snapshot(attachment_root),
            planned_paths=[".localsetup/lock.json", ".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "context":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        payload = build_agent_context(root, home=home, config=config)
        markdown = bool(config.output.markdown)
        _write_report(config.output.report, payload, markdown=markdown)
        _print_payload(payload, markdown=markdown)
        return 0 if not payload["blockers"] else 1

    if args.cmd == "generate-docs":
        print(json.dumps(generate_alias_outputs(root), indent=2))
        return 0

    if args.cmd == "plugin":
        if args.plugin_action == "list":
            issues = validate_plugin_pack_manifest(root)
            configs = []
            if not issues:
                configs = [
                    {
                        "id": config.plugin_id,
                        "display_name": config.display_name,
                        "description": config.description,
                        "category": config.category,
                        "source_pack": config.source_pack,
                    }
                    for config in load_plugin_pack_configs(root)
                    if args.platform in config.platforms
                ]
            _print_payload({"ok": not issues, "platform": args.platform, "plugin_packs": configs, "issues": issues})
            return 0 if not issues else 1
        if args.plugin_action == "plan":
            payload = plan_plugin_packs(root, args.plugin_packs, platform=args.platform)
            if args.output:
                payload["output"] = str(Path(args.output).expanduser())
            _print_payload(payload)
            return 0
        if args.plugin_action == "build":
            payload = build_codex_plugins(root, Path(args.output).expanduser(), args.plugin_packs)
            _print_payload(payload)
            return 0 if payload.get("ok") else 1
        if args.plugin_action == "validate":
            payload = validate_codex_plugin_path(Path(args.path).expanduser())
            _print_payload(payload)
            return 0 if payload.get("ok") else 1
        print(f"localsetup: unsupported plugin action: {args.plugin_action}", file=sys.stderr)
        return 2

    if args.cmd == "harness":
        if args.harness_topic == "repo-finalizer":
            target_root = _harness_target(args)
            if args.harness_action == "plan":
                payload = repo_finalizer_plan(root, target_root, mode=getattr(args, "mode", None))
            elif args.harness_action == "status":
                payload = repo_finalizer_status(root, target_root, mode=getattr(args, "mode", None))
            elif args.harness_action == "run":
                payload = repo_finalizer_run(
                    root,
                    target_root,
                    mode=getattr(args, "mode", None),
                    no_commit=args.no_commit,
                    checkpoint=args.checkpoint,
                    message=args.message,
                )
            else:
                print(f"localsetup: unsupported repo-finalizer action: {args.harness_action}", file=sys.stderr)
                return 2
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(repo_finalizer_payload_to_text(payload), end="")
            return 0 if payload.get("ok", True) else 1
        if args.harness_topic != "codex-heartbeat":
            print(f"localsetup: unsupported harness topic: {args.harness_topic}", file=sys.stderr)
            return 2
        target_root = _harness_target(args)
        if args.harness_action == "plan":
            payload = harness_plan(root, target_root)
        elif args.harness_action == "init":
            payload = harness_init(root, target_root)
        elif args.harness_action == "enable":
            payload = harness_enable(root, target_root, install_crontab=args.install_crontab, yes=args.yes)
        elif args.harness_action == "disable":
            payload = harness_disable(root, target_root, install_crontab=args.install_crontab, yes=args.yes)
        elif args.harness_action == "status":
            payload = harness_status(root, target_root)
        elif args.harness_action == "run":
            payload = harness_run(root, target_root, no_agent=args.no_agent, force=args.force)
        else:
            print(f"localsetup: unsupported heartbeat action: {args.harness_action}", file=sys.stderr)
            return 2
        print(harness_payload_to_text(payload))
        return 0 if payload.get("ok") else 1

    if args.cmd == "docs-align":
        tool = root / "_localsetup" / "tools" / "docs_alignment.py"
        command = [sys.executable, str(tool), "--repo-root", str(root), *args.docs_align_args]
        return subprocess.run(command, cwd=root).returncode

    if args.cmd == "context-index":
        tool = root / "_localsetup" / "tools" / "context_index.py"
        target_root = Path(getattr(args, "target_directory", None) or root).expanduser().resolve()
        command = [
            sys.executable,
            str(tool),
            "--repo",
            str(target_root),
            "--source-root",
            str(root),
            "--home",
            str(home),
            *args.context_index_args,
        ]
        return subprocess.run(command, cwd=target_root).returncode

    if args.cmd == "catalog":
        skills = []
        for skill in load_skill_catalog(root):
            skills.append(
                {
                    "name": skill.name,
                    "legacy_name": skill.legacy_name,
                    "description": skill.description,
                    "version": skill.version,
                    "class": skill.taxonomy_class,
                    "sort_priority": skill.sort_priority,
                    "tags": skill.tags,
                    "owner_scope": skill.owner_scope,
                    "packs": skill.packs,
                    "path": str(skill.path),
                }
            )
        payload = {
            "skills": skills,
            "workflows": [workflow.__dict__ | {"path": str(workflow.path)} for workflow in load_workflow_catalog(root)],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.cmd == "diff":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        payload = diff_plan_current(
            root,
            home=home,
            packs=config.packs,
            preset=config.preset,
            skills=config.skills,
            workflows=config.workflows,
            skill_classes=config.skill_classes,
            skill_tags=config.skill_tags,
            exclude_skills=config.exclude_skills,
            global_packs=config.global_packs,
            global_preset=config.global_preset,
            global_skills=config.global_skills,
            global_workflows=config.global_workflows,
            global_skill_classes=config.global_skill_classes,
            global_skill_tags=config.global_skill_tags,
            global_exclude_skills=config.global_exclude_skills,
            repo_packs=config.repo_packs,
            repo_preset=config.repo_preset,
            repo_skills=config.repo_skills,
            repo_workflows=config.repo_workflows,
            repo_skill_classes=config.repo_skill_classes,
            repo_skill_tags=config.repo_skill_tags,
            repo_exclude_skills=config.repo_exclude_skills,
            platform_ids=config.platforms,
            target_root=target_root,
            attach_mode=config.attach_mode,
        )
        _print_payload(payload)
        return 0

    if args.cmd == "skill":
        payload = skill_payload(root, args.query)
        _print_payload(payload)
        return 0 if payload["count"] else 1

    if args.cmd == "workflow":
        payload = workflow_payload(root, args.query)
        _print_payload(payload)
        return 0 if payload["count"] else 1

    if args.cmd == "why":
        _print_payload(pack_reasoning(root, args.packs))
        return 0

    if args.cmd == "graph":
        _print_payload(graph_payload(root))
        return 0

    if args.cmd == "adopt":
        target_root = Path(getattr(args, "target_directory", None) or root).expanduser().resolve()
        _print_payload(adopt_recommendations(target_root))
        return 0

    if args.cmd == "detach":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else root
        from .adapters import adapter_targets, legacy_global_roots, remove_managed_adapter_entries
        removed = []
        pack = load_pack_config(root)
        global_root = expand_user_path(pack.global_root, home)
        for target in adapter_targets(root, home, platform_ids=config.platforms, target_root=target_root):
            path = target["repo_path"]
            removed.extend(
                remove_managed_adapter_entries(
                    path,
                    global_root,
                    known_global_roots=legacy_global_roots(home),
                    recorded_packages=target.get("packages"),
                )
            )
        _print_payload({"removed": removed, "packages_preserved": True})
        return 0

    if args.cmd == "sbom":
        if args.installed:
            target_root = Path(getattr(args, "target_directory", None) or root).expanduser().resolve()
            payload = write_installed_sbom(root, target_root, Path(args.out))
        else:
            payload = write_source_sbom(root, Path(args.out))
        _print_payload(payload)
        return 0

    if args.cmd == "validate-catalog":
        issues = validate_manifest_schemas(root) + validate_plugin_pack_manifest(root) + validate_skill_catalog(root) + validate_workflow_catalog(root)
        print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if args.cmd == "scan-migration":
        print(json.dumps({"findings": scan_legacy_references(root, include_expected=args.include_expected)}, indent=2))
        return 0

    if args.cmd == "audit-global-first":
        target_root = Path(getattr(args, "target_directory", None)).expanduser().resolve() if getattr(args, "target_directory", None) else None
        payload = audit_global_first(root, home=home, target_root=target_root)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "hook-gate":
        result = run_maintainer_gate(root, Path(args.out), runner=args.runner)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

    if args.cmd == "version-plan":
        if args.push_stdin:
            plans = push_lines_to_plans(root, sys.stdin.read())
            print_json({"ok": all(plan["ok"] for plan in plans), "plans": plans})
            return 0 if all(plan["ok"] for plan in plans) else 1
        payload = plan_version(root, base=args.base, head=args.head, ref=args.ref)
        print_json(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "version-sync":
        plan = None
        target = args.target
        if not target:
            plan = plan_version(root, base=args.base, head=args.head)
            if not plan["ok"] and plan.get("release_type_required"):
                print_json(plan)
                return 1
            target = plan["target_version"]
        if args.check:
            payload = check_version_files(root, target)
            if plan:
                payload["plan"] = plan
            print_json(payload)
            return 0 if payload["ok"] else 1
        payload = sync_version_files(root, target)
        if args.stage:
            stage_version_files(root)
            payload["staged"] = True
        if args.commit:
            payload["commit"] = commit_version_sync(root, target)
            payload["commit_message"] = f"{VERSION_SYNC_PREFIX} {target}"
        if plan:
            payload["plan"] = plan
        print_json(payload)
        return 0

    if args.cmd == "publish-preflight":
        payload = publish_preflight(root, base=args.base, head=args.head, fix=args.fix)
        print_json(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "release-push":
        plan = plan_version(root)
        if not plan["ok"] and plan.get("release_type_required"):
            print_json(plan)
            return 1
        if plan["bump"] != "none" and not plan["ok"]:
            sync_version_files(root, plan["target_version"])
            commit_version_sync(root, plan["target_version"])
            plan = plan_version(root)
            if not plan["ok"] and plan.get("release_type_required"):
                print_json(plan)
                return 1
        push_args = args.push_args
        if push_args and push_args[0] == "--":
            push_args = push_args[1:]
        cmd = ["git", "push", *push_args] if push_args else ["git", "push"]
        completed = subprocess.run(cmd, cwd=root)
        return completed.returncode

    if args.cmd == "self-refresh":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else root
        git_pre = git_status_snapshot(target_root)
        packs_override = _split_csv(getattr(args, "packs", None)) if getattr(args, "packs", None) is not None else None
        platforms_override = _split_csv(getattr(args, "platforms", None)) if getattr(args, "platforms", None) is not None else None
        payload = _run_self_refresh(
            root,
            config,
            home,
            packs_override=packs_override,
            platforms_override=platforms_override,
            attach_mode_explicit=getattr(args, "mode", None) is not None,
        )
        _record_health_for_payload(
            root=root,
            home=home,
            target_root=target_root,
            operation="self-refresh",
            mode="apply",
            payload=payload,
            git_pre=git_pre,
            git_post=git_status_snapshot(target_root),
            planned_paths=[".localsetup/lock.json", ".localsetup/health.json", ".localsetup/AGENT_STATUS.md"],
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "install-hooks":
        subprocess.run(["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True)
        print_json({"ok": True, "core.hooksPath": ".githooks"})
        return 0

    if args.cmd == "register-shell":
        payload = register_shell_command(root, home=home)
        _print_payload(payload)
        return 0

    if args.cmd == "package":
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        payload = build_public_artifact(root, out)
        print(json.dumps(payload, indent=2))
        return 1 if payload.get("leaks") else 0

    if args.cmd == "verify-release":
        payload = verify_release_artifact(
            Path(args.artifact),
            sha256_path=Path(args.sha256) if args.sha256 else None,
            sbom_path=Path(args.sbom) if args.sbom else None,
            expected_commit=args.expected_commit,
            expected_tag=args.expected_tag,
        )
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if payload["ok"] else 1

    return 1


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        print(f"localsetup: {exc}", file=sys.stderr)
        return 2

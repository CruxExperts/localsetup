from __future__ import annotations

import argparse
import os
import json
from pathlib import Path
import subprocess
import sys

from .adapters import adapter_path_state, adapter_status
from .apply import apply_plan
from .config import DEPENDENCY_MODES, InstallConfig, config_to_dict, load_install_config, merge_cli_config
from .context import build_agent_context, render_markdown_report
from .conversion import convert_repo
from .dependencies import ensure_dependencies
from .doctor import run_doctor
from .docs import generate_alias_outputs
from .hooks import run_maintainer_gate
from .manifests import load_pack_config
from .manifests import load_platforms
from .lockfile import save_json, save_text
from .migration import conservative_migrate, scan_legacy_references
from .package import build_public_artifact
from .paths import expand_user_path
from .plan import build_install_plan
from .rollback import rollback
from .shell import SHIM_ENV, detect_invocation_target, register_shell_command, shell_registration_status
from .skills import load_skill_catalog, validate_skill_catalog
from .workflows import load_workflow_catalog, validate_workflow_catalog
from .verify import verify_install
from .wizard import run_wizard
from .versioning import (
    VERSION_SYNC_PREFIX,
    check_version_files,
    commit_version_sync,
    plan_version,
    print_json,
    push_lines_to_plans,
    stage_version_files,
    sync_version_files,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


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
    parser.add_argument("--json", action="store_true", default=None)
    parser.add_argument("--report")
    parser.add_argument("--backup-dir")
    parser.add_argument("--dependency-mode", choices=sorted(DEPENDENCY_MODES))
    if include_apply:
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--yes", action="store_true", dest="apply", help=argparse.SUPPRESS)


def _add_selector_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--packs", nargs="*")
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
    if args.cmd not in {"plan", "install", "update", "verify", "rollback", "adapters", "doctor", "migrate", "context", "convert"}:
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


def _all_configured_packs(repo_root: Path) -> list[str]:
    pack = load_pack_config(repo_root)
    return list(pack.packs.keys())


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
    dependency_info = ensure_dependencies(root, mode=config.dependency_mode) if config.dependency_mode != "prompt-only" else None
    plan = build_install_plan(
        root,
        home=home,
        packs=packs,
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
    parser = argparse.ArgumentParser(prog="localsetup-v3")
    parser.add_argument("--home")
    parser.add_argument("--repo", default=str(_repo_root()))
    parser.add_argument("--target-directory")
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan_p = sub.add_parser("plan")
    _add_config_flags(plan_p)
    _add_selector_flags(plan_p)

    install_p = sub.add_parser("install")
    _add_config_flags(install_p, include_apply=True)
    _add_selector_flags(install_p)

    verify_p = sub.add_parser("verify")
    _add_config_flags(verify_p)
    verify_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")

    rollback_p = sub.add_parser("rollback")
    _add_config_flags(rollback_p)
    rollback_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")

    update_p = sub.add_parser("update")
    _add_config_flags(update_p)
    _add_selector_flags(update_p)

    adapters_p = sub.add_parser("adapters")
    adapters_p.add_argument("--target-directory", default=argparse.SUPPRESS)
    adapters_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")
    configure_p = sub.add_parser("configure")
    _add_config_flags(configure_p)
    _add_selector_flags(configure_p)
    configure_p.add_argument("--home-override")

    doctor_p = sub.add_parser("doctor")
    _add_config_flags(doctor_p)
    doctor_p.add_argument("--packs", nargs="*")
    doctor_p.add_argument("--platforms", "--tools", nargs="*", dest="platforms")

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
    sub.add_parser("scan-migration")
    sub.add_parser("validate-catalog")
    sub.add_parser("generate-docs")
    docs_align_p = sub.add_parser("docs-align")
    docs_align_p.add_argument("docs_align_args", nargs=argparse.REMAINDER)

    hook_p = sub.add_parser("hook-gate")
    hook_p.add_argument("--out", default="/tmp/localsetup-v3-public.tar.gz")
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
    package_p.add_argument("--out", default="dist/localsetup-v3-public.tar.gz")

    args = parser.parse_args(argv)
    _inject_global_target(args)
    root = Path(args.repo).resolve()
    home = Path(args.home or Path.home()).expanduser().resolve()

    if args.cmd in {"plan", "install", "update"}:
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        attachment_root = target_root or root
        plan = build_install_plan(
            root,
            home=home,
            packs=config.packs,
            attach_mode=config.attach_mode,
            platform_ids=config.platforms,
            target_root=target_root,
        )
        detected_target = bool(getattr(args, "detected_target_directory", False))
        if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
            warnings = []
            if config.target_directory and not config.platforms and not detected_target:
                warnings.append("target directory was provided but no platforms were selected; plan is global-only with no repo adapters")
            payload = {
                "actions": [{"kind": a.kind, "path": str(a.path), "details": a.details} for a in plan.actions],
                "config": config_to_dict(config),
                "attachment": {
                    "target_root": str(attachment_root),
                    "platforms": plan.rollback_metadata.get("platforms", []),
                    "global_only": plan.rollback_metadata.get("global_only", False),
                },
                "warnings": warnings,
                "rollback": plan.rollback_metadata,
            }
            _write_report(config.output.report, payload)
            _print_payload(payload)
            return 0
        dependency_info = ensure_dependencies(root, mode=config.dependency_mode) if config.dependency_mode != "prompt-only" else None
        result = apply_plan(root, plan, home=home, dry_run=False, dependency_info=dependency_info, target_root=target_root)
        if dependency_info:
            result["dependencies"] = dependency_info
        result["attachment"] = {
            "target_root": str(attachment_root),
            "platforms": plan.rollback_metadata.get("platforms", []),
            "global_only": plan.rollback_metadata.get("global_only", False),
        }
        if config.target_directory and not config.platforms and not detected_target:
            result["warnings"] = ["target directory was provided but no platforms were selected; install was global-only with no repo adapters"]
        _write_report(config.output.report, result)
        _print_payload(result)
        return 0

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
            attach_mode=config.attach_mode,
            dependency_mode=config.dependency_mode,
            register_shell=not args.no_register_shell,
            color_mode=args.color,
            glyph_mode=args.glyphs,
        )

    if args.cmd == "verify":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        payload = verify_install(root, home=home, platform_ids=config.platforms, target_root=target_root)
        _write_report(config.output.report, payload)
        _print_payload(payload)
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
        print(
            json.dumps(
                adapter_status(
                    root,
                    home,
                    expand_user_path(pack.global_root, home),
                    platform_ids=_split_csv(args.platforms),
                    target_root=target_root,
                ),
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
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        payload = run_doctor(
            root,
            home=home,
            packs=config.packs,
            platform_ids=config.platforms,
            dependency_mode=config.dependency_mode,
            target_root=target_root,
        )
        payload["shell_registration"] = shell_registration_status(root, home=home)
        if payload["shell_registration"]["warnings"]:
            payload["warnings"].extend(payload["shell_registration"]["warnings"])
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "migrate":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        apply_migration = not args.dry_run and config.migration_mode != "report-only"
        payload = conservative_migrate(
            root,
            home=home,
            platform_ids=config.platforms,
            target_root=target_root,
            backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
            apply=apply_migration,
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "convert":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        target_root = Path(config.target_directory).expanduser().resolve() if config.target_directory else None
        payload = convert_repo(
            root,
            home=home,
            packs=config.packs,
            platform_ids=config.platforms,
            attach_mode=config.attach_mode,
            target_root=target_root,
            backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
            dependency_mode=config.dependency_mode,
            apply=bool(args.apply),
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

    if args.cmd == "docs-align":
        tool = root / "_localsetup" / "tools" / "docs_alignment.py"
        command = [sys.executable, str(tool), "--repo-root", str(root), *args.docs_align_args]
        return subprocess.run(command, cwd=root).returncode

    if args.cmd == "catalog":
        payload = {
            "skills": [skill.__dict__ | {"path": str(skill.path)} for skill in load_skill_catalog(root)],
            "workflows": [workflow.__dict__ | {"path": str(workflow.path)} for workflow in load_workflow_catalog(root)],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.cmd == "validate-catalog":
        issues = validate_skill_catalog(root) + validate_workflow_catalog(root)
        print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if args.cmd == "scan-migration":
        print(json.dumps({"findings": scan_legacy_references(root)}, indent=2))
        return 0

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

    if args.cmd == "release-push":
        plan = plan_version(root)
        if plan["bump"] != "none" and not plan["ok"]:
            sync_version_files(root, plan["target_version"])
            commit_version_sync(root, plan["target_version"])
            plan = plan_version(root)
        push_args = args.push_args
        if push_args and push_args[0] == "--":
            push_args = push_args[1:]
        cmd = ["git", "push", *push_args] if push_args else ["git", "push"]
        completed = subprocess.run(cmd, cwd=root)
        return completed.returncode

    if args.cmd == "self-refresh":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
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
        print(json.dumps(build_public_artifact(root, out), indent=2))
        return 0

    return 1


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except Exception as exc:
        print(f"localsetup-v3: {exc}", file=sys.stderr)
        return 2

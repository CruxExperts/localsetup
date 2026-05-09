from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .adapters import adapter_status
from .apply import apply_plan
from .config import DEPENDENCY_MODES, InstallConfig, config_to_dict, load_install_config, merge_cli_config
from .context import build_agent_context, render_markdown_report
from .dependencies import ensure_dependencies
from .doctor import run_doctor
from .docs import generate_alias_outputs
from .hooks import run_maintainer_gate
from .manifests import load_pack_config
from .lockfile import save_json, save_text
from .migration import conservative_migrate, scan_legacy_references
from .package import build_public_artifact
from .paths import expand_user_path
from .plan import build_install_plan
from .rollback import rollback
from .skills import load_skill_catalog, validate_skill_catalog
from .verify import verify_install


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
    parser.add_argument("--json", action="store_true", default=None)
    parser.add_argument("--report")
    parser.add_argument("--backup-dir")
    parser.add_argument("--dependency-mode", choices=sorted(DEPENDENCY_MODES))
    if include_apply:
        parser.add_argument("--apply", action="store_true")


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


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localsetup-v3")
    parser.add_argument("--home")
    parser.add_argument("--repo", default=str(_repo_root()))
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan_p = sub.add_parser("plan")
    _add_config_flags(plan_p)
    plan_p.add_argument("--packs", nargs="*")
    plan_p.add_argument("--mode", choices=["symlink", "portable"])
    plan_p.add_argument("--platforms", nargs="*")

    install_p = sub.add_parser("install")
    _add_config_flags(install_p, include_apply=True)
    install_p.add_argument("--packs", nargs="*")
    install_p.add_argument("--mode", choices=["symlink", "portable"])
    install_p.add_argument("--platforms", nargs="*")

    verify_p = sub.add_parser("verify")
    _add_config_flags(verify_p)
    verify_p.add_argument("--platforms", nargs="*")

    rollback_p = sub.add_parser("rollback")
    _add_config_flags(rollback_p)
    rollback_p.add_argument("--platforms", nargs="*")

    update_p = sub.add_parser("update")
    _add_config_flags(update_p)
    update_p.add_argument("--packs", nargs="*")
    update_p.add_argument("--mode", choices=["symlink", "portable"])
    update_p.add_argument("--platforms", nargs="*")

    adapters_p = sub.add_parser("adapters")
    adapters_p.add_argument("--platforms", nargs="*")
    configure_p = sub.add_parser("configure")
    _add_config_flags(configure_p)
    configure_p.add_argument("--packs", nargs="*")
    configure_p.add_argument("--mode", choices=["symlink", "portable"])
    configure_p.add_argument("--platforms", nargs="*")
    configure_p.add_argument("--home-override")

    doctor_p = sub.add_parser("doctor")
    _add_config_flags(doctor_p)
    doctor_p.add_argument("--packs", nargs="*")
    doctor_p.add_argument("--platforms", nargs="*")

    migrate_p = sub.add_parser("migrate")
    _add_config_flags(migrate_p)
    migrate_p.add_argument("--platforms", nargs="*")
    migrate_p.add_argument("--dry-run", action="store_true")

    context_p = sub.add_parser("context")
    _add_config_flags(context_p)
    context_p.add_argument("--packs", nargs="*")
    context_p.add_argument("--mode", choices=["symlink", "portable"])
    context_p.add_argument("--platforms", nargs="*")
    context_p.add_argument("--markdown", action="store_true", default=None)

    sub.add_parser("catalog")
    sub.add_parser("scan-migration")
    sub.add_parser("validate-catalog")
    sub.add_parser("generate-docs")

    hook_p = sub.add_parser("hook-gate")
    hook_p.add_argument("--out", default="/tmp/localsetup-v3-public.tar.gz")
    hook_p.add_argument("--runner")

    package_p = sub.add_parser("package")
    package_p.add_argument("--out", default="dist/localsetup-v3-public.tar.gz")

    args = parser.parse_args(argv)
    root = Path(args.repo).resolve()
    home = Path(args.home or Path.home()).expanduser().resolve()

    if args.cmd in {"plan", "install", "update"}:
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        plan = build_install_plan(
            root,
            home=home,
            packs=config.packs,
            attach_mode=config.attach_mode,
            platform_ids=config.platforms,
        )
        if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
            payload = {
                "actions": [{"kind": a.kind, "path": str(a.path), "details": a.details} for a in plan.actions],
                "config": config_to_dict(config),
                "rollback": plan.rollback_metadata,
            }
            _write_report(config.output.report, payload)
            _print_payload(payload)
            return 0
        dependency_info = ensure_dependencies(root, mode=config.dependency_mode) if config.dependency_mode != "prompt-only" else None
        result = apply_plan(root, plan, home=home, dry_run=False, dependency_info=dependency_info)
        if dependency_info:
            result["dependencies"] = dependency_info
        _write_report(config.output.report, result)
        _print_payload(result)
        return 0

    if args.cmd == "verify":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        payload = verify_install(root, home=home, platform_ids=config.platforms)
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "rollback":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        payload = rollback(root, home=home, platform_ids=config.platforms)
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0

    if args.cmd == "adapters":
        pack = load_pack_config(root)
        print(
            json.dumps(
                adapter_status(root, home, expand_user_path(pack.global_root, home), platform_ids=_split_csv(args.platforms)),
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
        payload = run_doctor(
            root,
            home=home,
            packs=config.packs,
            platform_ids=config.platforms,
            dependency_mode=config.dependency_mode,
        )
        _write_report(config.output.report, payload)
        _print_payload(payload)
        return 0 if payload["ok"] else 1

    if args.cmd == "migrate":
        config = _resolved_config(args, home)
        home = Path(config.home or home).expanduser().resolve()
        apply_migration = not args.dry_run and config.migration_mode != "report-only"
        payload = conservative_migrate(
            root,
            home=home,
            platform_ids=config.platforms,
            backup_dir=Path(config.backup_dir).expanduser().resolve() if config.backup_dir else None,
            apply=apply_migration,
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

    if args.cmd == "catalog":
        print(json.dumps([skill.__dict__ | {"path": str(skill.path)} for skill in load_skill_catalog(root)], indent=2))
        return 0

    if args.cmd == "validate-catalog":
        issues = validate_skill_catalog(root)
        print(json.dumps({"ok": not issues, "issues": issues}, indent=2))
        return 0 if not issues else 1

    if args.cmd == "scan-migration":
        print(json.dumps({"findings": scan_legacy_references(root)}, indent=2))
        return 0

    if args.cmd == "hook-gate":
        result = run_maintainer_gate(root, Path(args.out), runner=args.runner)
        print(json.dumps(result, indent=2))
        return 0 if result["ok"] else 1

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

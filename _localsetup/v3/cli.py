from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import adapter_status
from .apply import apply_plan
from .docs import generate_alias_outputs
from .hooks import run_maintainer_gate
from .manifests import load_pack_config
from .migration import scan_legacy_references
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="localsetup-v3")
    parser.add_argument("--home", default=str(Path.home()))
    parser.add_argument("--repo", default=str(_repo_root()))
    sub = parser.add_subparsers(dest="cmd", required=True)

    plan_p = sub.add_parser("plan")
    plan_p.add_argument("--packs", nargs="*", default=["core"])
    plan_p.add_argument("--mode", choices=["symlink", "portable"], default="symlink")
    plan_p.add_argument("--platforms", nargs="*")

    install_p = sub.add_parser("install")
    install_p.add_argument("--packs", nargs="*", default=["core"])
    install_p.add_argument("--apply", action="store_true")
    install_p.add_argument("--mode", choices=["symlink", "portable"], default="symlink")
    install_p.add_argument("--platforms", nargs="*")

    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--platforms", nargs="*")

    rollback_p = sub.add_parser("rollback")
    rollback_p.add_argument("--platforms", nargs="*")

    update_p = sub.add_parser("update")
    update_p.add_argument("--packs", nargs="*", default=["core"])
    update_p.add_argument("--mode", choices=["symlink", "portable"], default="symlink")
    update_p.add_argument("--platforms", nargs="*")

    adapters_p = sub.add_parser("adapters")
    adapters_p.add_argument("--platforms", nargs="*")
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
    home = Path(args.home)

    if args.cmd in {"plan", "install", "update"}:
        plan = build_install_plan(
            root,
            home=home,
            packs=_split_csv(getattr(args, "packs", ["core"])),
            attach_mode=getattr(args, "mode", "symlink"),
            platform_ids=_split_csv(getattr(args, "platforms", None)),
        )
        if args.cmd == "plan" or (args.cmd == "install" and not args.apply):
            print(json.dumps({"actions": [a.kind for a in plan.actions], "rollback": plan.rollback_metadata}, indent=2))
            return 0
        result = apply_plan(root, plan, home=home, dry_run=False)
        print(json.dumps(result, indent=2))
        return 0

    if args.cmd == "verify":
        print(json.dumps(verify_install(root, home=home, platform_ids=_split_csv(args.platforms)), indent=2))
        return 0

    if args.cmd == "rollback":
        print(json.dumps(rollback(root, home=home, platform_ids=_split_csv(args.platforms)), indent=2))
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

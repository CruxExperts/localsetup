#!/usr/bin/env python3
"""OmniRoute administration CLI.

Purpose:
    Provide a safe, automation-first command surface for OmniRoute control-plane
    administration. Supports health checks, snapshot, plan, apply, reconcile,
    backup, restore, and targeted mutation actions.

Examples:
    python3 omniroute_admin.py health --base-url http://localhost:20128
    python3 omniroute_admin.py snapshot --out state/live.json
    python3 omniroute_admin.py plan --desired manifests/prod.json --out state/plan.json
    python3 omniroute_admin.py apply --plan state/plan.json --yes
    python3 omniroute_admin.py reconcile --desired manifests/prod.json --mode guarded
    python3 omniroute_admin.py backup --out state/backups/manual.json

Notes:
    - Reads secrets only from environment variables.
    - Never prints token values.
    - Destructive actions require explicit confirmation flags.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

# Resolve _localsetup/lib for dependency policy helper.
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["requests"])

from lib.omniroute_admin.audit import AuditLogger
from lib.omniroute_admin.client import OmniRouteAdminClient
from lib.omniroute_admin.reconcile import (
    apply_plan,
    build_plan,
    load_desired_manifest,
    render_plan_summary,
)
from lib.omniroute_admin.safety import require_destructive_ack
from lib.omniroute_admin.util import (
    ensure_parent_dir,
    error,
    load_json,
    load_text_env,
    now_iso,
    print_json,
    sanitize_path,
    write_json,
)
from lib.omniroute_admin.validate import validate_desired_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="OmniRoute administration automation CLI"
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128"),
        help=(
            "OmniRoute base URL "
            "(default: OMNIROUTE_BASE_URL or http://localhost:20128)"
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default="OMNIROUTE_API_KEY",
        help="Environment variable that stores bearer API key (default: OMNIROUTE_API_KEY)",
    )
    parser.add_argument(
        "--management-cookie-env",
        default="OMNIROUTE_MGMT_COOKIE",
        help="Environment variable with management cookie header value (example: auth_token=<token>)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="Per-request timeout in seconds (default: 20)",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=3,
        help="Retry attempts for transient failures (default: 3)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("health", help="Check OmniRoute health endpoint")

    provider = sub.add_parser("provider", help="Provider administration operations")
    provider_sub = provider.add_subparsers(dest="provider_action", required=True)
    provider_sub.add_parser("list", help="List providers")
    provider_get = provider_sub.add_parser("get", help="Get provider by id")
    provider_get.add_argument("--id", required=True, help="Provider identifier")
    provider_create = provider_sub.add_parser(
        "create", help="Create provider from JSON payload"
    )
    provider_create.add_argument(
        "--payload", required=True, help="JSON file payload path"
    )
    provider_update = provider_sub.add_parser(
        "update", help="Update provider from JSON payload"
    )
    provider_update.add_argument("--id", required=True, help="Provider identifier")
    provider_update.add_argument(
        "--payload", required=True, help="JSON file payload path"
    )
    provider_delete = provider_sub.add_parser("delete", help="Delete provider")
    provider_delete.add_argument("--id", required=True, help="Provider identifier")
    provider_delete.add_argument("--yes", action="store_true", help="Confirm delete")
    provider_delete.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for destructive provider deletion",
    )

    combo = sub.add_parser("combo", help="Routing combo administration operations")
    combo_sub = combo.add_subparsers(dest="combo_action", required=True)
    combo_sub.add_parser("list", help="List combos")
    combo_get = combo_sub.add_parser("get", help="Get combo by id")
    combo_get.add_argument("--id", required=True, help="Combo identifier")
    combo_create = combo_sub.add_parser("create", help="Create combo from JSON payload")
    combo_create.add_argument("--payload", required=True, help="JSON file payload path")
    combo_update = combo_sub.add_parser("update", help="Update combo from JSON payload")
    combo_update.add_argument("--id", required=True, help="Combo identifier")
    combo_update.add_argument("--payload", required=True, help="JSON file payload path")
    combo_delete = combo_sub.add_parser("delete", help="Delete combo")
    combo_delete.add_argument("--id", required=True, help="Combo identifier")
    combo_delete.add_argument("--yes", action="store_true", help="Confirm delete")
    combo_delete.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for destructive combo deletion",
    )

    alias = sub.add_parser("alias", help="Model alias administration operations")
    alias_sub = alias.add_subparsers(dest="alias_action", required=True)
    alias_sub.add_parser("list", help="List aliases")
    alias_create = alias_sub.add_parser("create", help="Create alias from JSON payload")
    alias_create.add_argument("--payload", required=True, help="JSON file payload path")
    alias_update = alias_sub.add_parser("update", help="Update alias from JSON payload")
    alias_update.add_argument("--id", required=True, help="Alias identifier")
    alias_update.add_argument("--payload", required=True, help="JSON file payload path")
    alias_delete = alias_sub.add_parser("delete", help="Delete alias")
    alias_delete.add_argument("--id", required=True, help="Alias identifier")
    alias_delete.add_argument("--yes", action="store_true", help="Confirm delete")
    alias_delete.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for destructive alias deletion",
    )

    budget = sub.add_parser("budget", help="Usage budget operations")
    budget_sub = budget.add_subparsers(dest="budget_action", required=True)
    budget_sub.add_parser("get", help="Get current budget")
    budget_set = budget_sub.add_parser("set", help="Set budget from JSON payload")
    budget_set.add_argument("--payload", required=True, help="JSON file payload path")

    key = sub.add_parser("key", help="API key lifecycle operations")
    key_sub = key.add_subparsers(dest="key_action", required=True)
    key_sub.add_parser("list", help="List key metadata")
    key_create = key_sub.add_parser("create", help="Create key from JSON payload")
    key_create.add_argument("--payload", required=True, help="JSON file payload path")
    key_delete = key_sub.add_parser("delete", help="Delete key")
    key_delete.add_argument("--id", required=True, help="Key identifier")
    key_delete.add_argument("--yes", action="store_true", help="Confirm delete")
    key_delete.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for destructive key deletion",
    )

    snap = sub.add_parser("snapshot", help="Collect normalized live admin state")
    snap.add_argument("--out", required=True, help="Output JSON file path")

    val = sub.add_parser("validate", help="Validate desired state manifest only")
    val.add_argument("--desired", required=True, help="Desired manifest JSON path")

    plan = sub.add_parser("plan", help="Compute plan from desired state")
    plan.add_argument("--desired", required=True, help="Desired manifest JSON path")
    plan.add_argument("--out", required=True, help="Plan output JSON path")

    apply_cmd = sub.add_parser("apply", help="Apply an existing plan")
    apply_cmd.add_argument("--plan", required=True, help="Plan JSON path")
    apply_cmd.add_argument("--yes", action="store_true", help="Confirm apply execution")
    apply_cmd.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Allow delete operations from plan",
    )

    rec = sub.add_parser(
        "reconcile", help="Plan and optionally apply drift reconciliation"
    )
    rec.add_argument("--desired", required=True, help="Desired manifest JSON path")
    rec.add_argument(
        "--mode",
        choices=["report", "guarded", "enforce"],
        default="guarded",
        help="report=no mutations, guarded=mutate non-destructive only, enforce=allow destructive if approved",
    )
    rec.add_argument("--out", help="Optional plan output JSON path")
    rec.add_argument("--yes", action="store_true", help="Confirm mutation execution")
    rec.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Permit delete operations in enforce mode",
    )

    bkp = sub.add_parser("backup", help="Create DB backup via /api/db-backups")
    bkp.add_argument("--out", help="Optional output JSON path")

    rst = sub.add_parser("restore", help="Restore DB backup by backup id")
    rst.add_argument("--backup-id", required=True, help="Backup identifier")
    rst.add_argument("--yes", action="store_true", help="Confirm restore")
    rst.add_argument(
        "--allow-destructive",
        action="store_true",
        help="Required for restore because it is destructive",
    )

    return parser


def build_client(args: argparse.Namespace) -> OmniRouteAdminClient:
    api_key = load_text_env(args.api_key_env)
    mgmt_cookie = load_text_env(args.management_cookie_env)
    return OmniRouteAdminClient(
        base_url=args.base_url,
        api_key=api_key,
        management_cookie=mgmt_cookie,
        timeout=args.timeout,
        retries=args.retries,
    )


def command_health(client: OmniRouteAdminClient) -> int:
    result = client.health()
    print_json(result)
    return 0


def _load_payload_file(path_raw: str) -> dict[str, Any]:
    payload = load_json(sanitize_path(path_raw))
    if not isinstance(payload, dict):
        raise ValueError("payload file must contain a JSON object")
    return payload


def _confirm_single_delete(
    resource_name: str,
    resource_id: str,
    yes: bool,
    allow_destructive: bool,
) -> None:
    plan: dict[str, Any] = {
        "operations": [
            {
                "resource": resource_name,
                "action": "delete",
                "id": resource_id,
                "destructive": True,
            }
        ]
    }
    require_destructive_ack(
        plan=plan,
        confirmed=yes,
        allow_destructive=allow_destructive,
        action_name=f"delete {resource_name}",
    )


def command_provider(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.provider_action
    if action == "list":
        print_json(client.list_providers())
        return 0
    if action == "get":
        print_json(client.get_provider(args.id))
        return 0
    if action == "create":
        print_json(client.create_provider(_load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_provider(args.id, _load_payload_file(args.payload)))
        return 0
    if action == "delete":
        _confirm_single_delete("provider", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_provider(args.id))
        return 0
    error("Unknown provider action", details=str(action))
    return 2


def command_combo(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.combo_action
    if action == "list":
        print_json(client.list_combos())
        return 0
    if action == "get":
        print_json(client.get_combo(args.id))
        return 0
    if action == "create":
        print_json(client.create_combo(_load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_combo(args.id, _load_payload_file(args.payload)))
        return 0
    if action == "delete":
        _confirm_single_delete("combo", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_combo(args.id))
        return 0
    error("Unknown combo action", details=str(action))
    return 2


def command_alias(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.alias_action
    if action == "list":
        print_json(client.list_aliases())
        return 0
    if action == "create":
        print_json(client.create_alias(_load_payload_file(args.payload)))
        return 0
    if action == "update":
        print_json(client.update_alias(args.id, _load_payload_file(args.payload)))
        return 0
    if action == "delete":
        _confirm_single_delete("alias", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_alias(args.id))
        return 0
    error("Unknown alias action", details=str(action))
    return 2


def command_budget(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.budget_action
    if action == "get":
        print_json(client.get_budget())
        return 0
    if action == "set":
        print_json(client.set_budget(_load_payload_file(args.payload)))
        return 0
    error("Unknown budget action", details=str(action))
    return 2


def command_key(client: OmniRouteAdminClient, args: argparse.Namespace) -> int:
    action = args.key_action
    if action == "list":
        print_json(client.list_keys())
        return 0
    if action == "create":
        print_json(client.create_key(_load_payload_file(args.payload)))
        return 0
    if action == "delete":
        _confirm_single_delete("key", args.id, args.yes, args.allow_destructive)
        print_json(client.delete_key(args.id))
        return 0
    error("Unknown key action", details=str(action))
    return 2


def command_snapshot(
    client: OmniRouteAdminClient, out_path: str, audit: AuditLogger
) -> int:
    snapshot = client.collect_snapshot()
    path = sanitize_path(out_path)
    ensure_parent_dir(path)
    write_json(path, snapshot)
    audit.log("snapshot", {"out": str(path), "sections": sorted(snapshot.keys())})
    print(f"[OK] Snapshot written to {path}")
    return 0


def command_validate(desired_path: str) -> int:
    desired = load_desired_manifest(sanitize_path(desired_path))
    issues = validate_desired_manifest(desired)
    if issues:
        print("[FAIL] Manifest validation failed:")
        for issue in issues:
            print(f"- {issue}")
        return 2
    print("[OK] Manifest is valid")
    return 0


def command_plan(
    client: OmniRouteAdminClient,
    desired_path: str,
    out_path: str,
    audit: AuditLogger,
) -> int:
    desired = load_desired_manifest(sanitize_path(desired_path))
    issues = validate_desired_manifest(desired)
    if issues:
        error("Desired manifest validation failed", details="; ".join(issues))
        return 2

    live = client.collect_snapshot()
    plan = build_plan(live, desired)
    if plan.get("blocked"):
        error(
            "Plan blocked due to incomplete live snapshot",
            details=str(plan.get("errors", {})),
        )
        print_json(plan)
        return 2

    plan_path = sanitize_path(out_path)
    ensure_parent_dir(plan_path)
    write_json(plan_path, plan)
    audit.log(
        "plan",
        {
            "desired": str(desired_path),
            "out": str(plan_path),
            "summary": render_plan_summary(plan),
        },
    )
    print("[OK] Plan created")
    print_json({"summary": render_plan_summary(plan), "plan_file": str(plan_path)})
    return 0


def command_apply(
    client: OmniRouteAdminClient,
    plan_path: str,
    yes: bool,
    allow_destructive: bool,
    audit: AuditLogger,
) -> int:
    plan = load_json(sanitize_path(plan_path))
    if not isinstance(plan, dict):
        error("Plan file is not a JSON object")
        return 2

    require_destructive_ack(
        plan=plan,
        confirmed=yes,
        allow_destructive=allow_destructive,
        action_name="apply",
    )

    result = apply_plan(client, plan, allow_destructive=allow_destructive)
    audit.log("apply", {"plan": str(plan_path), "result": result})
    print_json(result)
    return 0 if result.get("ok", False) else 1


def command_reconcile(
    client: OmniRouteAdminClient,
    desired_path: str,
    mode: str,
    out_path: str | None,
    yes: bool,
    allow_destructive: bool,
    audit: AuditLogger,
) -> int:
    desired = load_desired_manifest(sanitize_path(desired_path))
    issues = validate_desired_manifest(desired)
    if issues:
        error("Desired manifest validation failed", details="; ".join(issues))
        return 2

    live = client.collect_snapshot()
    plan = build_plan(live, desired)
    if plan.get("blocked"):
        error(
            "Reconcile blocked due to incomplete live snapshot",
            details=str(plan.get("errors", {})),
        )
        print_json(plan)
        return 2

    summary = render_plan_summary(plan)

    if out_path:
        out = sanitize_path(out_path)
        ensure_parent_dir(out)
        write_json(out, plan)

    audit.log("reconcile_plan", {"mode": mode, "summary": summary})

    if mode == "report":
        print_json({"mode": mode, "summary": summary, "plan": plan})
        return 0

    if mode == "enforce":
        require_destructive_ack(
            plan=plan,
            confirmed=yes,
            allow_destructive=allow_destructive,
            action_name=f"reconcile ({mode})",
            require_confirmation=True,
        )
    else:
        if not yes:
            raise ValueError(
                "reconcile (guarded) requires explicit confirmation with --yes"
            )

    apply_allow_destructive = mode == "enforce" and allow_destructive
    result = apply_plan(client, plan, allow_destructive=apply_allow_destructive)
    audit.log("reconcile_apply", {"mode": mode, "result": result})
    print_json({"mode": mode, "summary": summary, "result": result})
    return 0 if result.get("ok", False) else 1


def command_backup(
    client: OmniRouteAdminClient, out_path: str | None, audit: AuditLogger
) -> int:
    result = client.create_backup()
    audit.log("backup", {"result": result})
    if out_path:
        path = sanitize_path(out_path)
        ensure_parent_dir(path)
        write_json(path, result)
    print_json(result)
    return 0


def command_restore(
    client: OmniRouteAdminClient,
    backup_id: str,
    yes: bool,
    allow_destructive: bool,
    audit: AuditLogger,
) -> int:
    dummy_plan: dict[str, Any] = {
        "operations": [
            {
                "resource": "db_backup",
                "action": "restore",
                "id": backup_id,
                "destructive": True,
            }
        ]
    }
    require_destructive_ack(
        plan=dummy_plan,
        confirmed=yes,
        allow_destructive=allow_destructive,
        action_name="restore",
    )
    result = client.restore_backup(backup_id)
    audit.log("restore", {"backup_id": backup_id, "result": result})
    print_json(result)
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    audit = AuditLogger(run_id=now_iso().replace(":", "-"))

    try:
        if args.command == "validate":
            return command_validate(args.desired)

        client = build_client(args)

        if args.command == "health":
            return command_health(client)
        if args.command == "provider":
            return command_provider(client, args)
        if args.command == "combo":
            return command_combo(client, args)
        if args.command == "alias":
            return command_alias(client, args)
        if args.command == "budget":
            return command_budget(client, args)
        if args.command == "key":
            return command_key(client, args)
        if args.command == "snapshot":
            return command_snapshot(client, args.out, audit)
        if args.command == "plan":
            return command_plan(client, args.desired, args.out, audit)
        if args.command == "apply":
            return command_apply(
                client, args.plan, args.yes, args.allow_destructive, audit
            )
        if args.command == "reconcile":
            return command_reconcile(
                client,
                desired_path=args.desired,
                mode=args.mode,
                out_path=args.out,
                yes=args.yes,
                allow_destructive=args.allow_destructive,
                audit=audit,
            )
        if args.command == "backup":
            return command_backup(client, args.out, audit)
        if args.command == "restore":
            return command_restore(
                client, args.backup_id, args.yes, args.allow_destructive, audit
            )

        error("Unknown command", details=str(args.command))
        return 2
    except Exception as exc:  # explicit boundary for actionable stderr
        error(
            "Unhandled failure in omniroute_admin",
            details=f"{type(exc).__name__}: {exc}",
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

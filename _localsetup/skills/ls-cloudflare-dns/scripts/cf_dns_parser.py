"""Argument parser construction for the Cloudflare DNS CLI."""

from __future__ import annotations

import argparse
from typing import Any, Mapping

from cf_dns_support import DEFAULT_API_BASE

def add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Cloudflare API base URL; override for mocks.")
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout in seconds.")
    parser.add_argument("--retries", type=int, default=2, help="Retries for 429/5xx responses.")
    parser.add_argument("--output", choices=("json", "table"), default="json", help="Output format. JSON is deterministic default.")

def add_apply_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--apply", action="store_true", help="Apply the mutation. Without this, mutations emit a dry-run plan.")
    parser.add_argument("--confirm", default="", help="Required exact confirmation phrase for --apply.")
    parser.add_argument("--plan-hash", help="Canonical SHA-256 plan hash from dry-run output.")
    parser.add_argument("--snapshot-waiver", action="store_true", help="Explicitly waive snapshot requirement for this operation.")
    parser.set_defaults(require_plan_hash=True)

def add_record_body_args(parser: argparse.ArgumentParser, *, required: bool = True) -> None:
    parser.add_argument("--type", required=False, help="DNS record type.")
    parser.add_argument("--name", required=required, help="DNS record name.")
    parser.add_argument("--content", required=required, help="DNS record content.")
    parser.add_argument("--ttl", type=int, help="Record TTL; use 1 for automatic.")
    proxied = parser.add_mutually_exclusive_group()
    proxied.add_argument("--proxied", dest="proxied", action="store_true", help="Proxy through Cloudflare.")
    proxied.add_argument("--dns-only", dest="proxied", action="store_false", help="Disable Cloudflare proxy.")
    parser.set_defaults(proxied=None)
    parser.add_argument("--priority", type=int, help="MX/SRV priority.")
    parser.add_argument("--comment", help="Cloudflare record comment.")
    parser.add_argument("--tag", dest="tags", action="append", help="Cloudflare record tag. Repeatable.")

def set_func(parser: argparse.ArgumentParser, func: Any) -> None:
    parser.set_defaults(func=func)

def build_parser(commands: Mapping[str, Any]) -> argparse.ArgumentParser:
    cmd_auth_verify = commands["cmd_auth_verify"]
    cmd_permissions_summarize = commands["cmd_permissions_summarize"]
    cmd_zones_list = commands["cmd_zones_list"]
    cmd_zones_get = commands["cmd_zones_get"]
    cmd_zone_mutation = commands["cmd_zone_mutation"]
    cmd_zone_activation_check = commands["cmd_zone_activation_check"]
    cmd_dns_settings_get = commands["cmd_dns_settings_get"]
    cmd_dns_settings_patch = commands["cmd_dns_settings_patch"]
    cmd_zone_settings_list = commands["cmd_zone_settings_list"]
    cmd_zone_settings_get = commands["cmd_zone_settings_get"]
    cmd_zone_settings_patch = commands["cmd_zone_settings_patch"]
    cmd_records_list = commands["cmd_records_list"]
    cmd_records_find = commands["cmd_records_find"]
    cmd_records_get = commands["cmd_records_get"]
    cmd_records_create = commands["cmd_records_create"]
    cmd_records_update = commands["cmd_records_update"]
    cmd_records_delete = commands["cmd_records_delete"]
    cmd_records_upsert = commands["cmd_records_upsert"]
    cmd_records_export = commands["cmd_records_export"]
    cmd_records_import = commands["cmd_records_import"]
    cmd_records_batch_plan = commands["cmd_records_batch_plan"]
    cmd_records_batch_apply = commands["cmd_records_batch_apply"]
    cmd_scan = commands["cmd_scan"]
    cmd_snapshot_create = commands["cmd_snapshot_create"]
    cmd_snapshot_create_all = commands["cmd_snapshot_create_all"]
    cmd_snapshot_diff = commands["cmd_snapshot_diff"]
    cmd_plan_diff_live = commands["cmd_plan_diff_live"]

    parser = argparse.ArgumentParser(description="Manage Cloudflare DNS using direct v4 REST API calls.")
    add_common(parser)
    sub = parser.add_subparsers(dest="resource", required=True)

    auth = sub.add_parser("auth", help="Token verification commands.")
    auth_sub = auth.add_subparsers(dest="action", required=True)
    set_func(auth_sub.add_parser("verify", help="Verify the API token."), cmd_auth_verify)

    permissions = sub.add_parser("permissions", help="Permission guidance.")
    perm_sub = permissions.add_subparsers(dest="action", required=True)
    set_func(perm_sub.add_parser("summarize", help="Summarize recommended token scopes."), cmd_permissions_summarize)

    zones = sub.add_parser("zones", help="Cloudflare zone operations.")
    zones_sub = zones.add_subparsers(dest="action", required=True)
    z_list = zones_sub.add_parser("list")
    z_list.add_argument("--name")
    z_list.add_argument("--status")
    z_list.add_argument("--account-id")
    z_list.add_argument("--all", action="store_true")
    z_list.add_argument("--limit", type=int, default=100)
    set_func(z_list, cmd_zones_list)
    z_get = zones_sub.add_parser("get")
    z_get.add_argument("zone")
    set_func(z_get, cmd_zones_get)
    z_create = zones_sub.add_parser("create")
    z_create.add_argument("--account-id", required=True)
    z_create.add_argument("--name", required=True)
    z_create.add_argument("--type", default="full")
    add_apply_flags(z_create)
    set_func(z_create, lambda args: cmd_zone_mutation(args, "create"))
    z_edit = zones_sub.add_parser("edit")
    z_edit.add_argument("zone")
    z_edit.add_argument("--paused", action="store_true")
    z_edit.add_argument("--vanity-name-server", dest="vanity_name_servers", action="append")
    add_apply_flags(z_edit)
    set_func(z_edit, lambda args: cmd_zone_mutation(args, "edit"))
    z_delete = zones_sub.add_parser("delete")
    z_delete.add_argument("zone")
    add_apply_flags(z_delete)
    set_func(z_delete, lambda args: cmd_zone_mutation(args, "delete"))
    z_activation = zones_sub.add_parser("activation-check")
    z_activation.add_argument("zone")
    set_func(z_activation, cmd_zone_activation_check)

    dns_settings = sub.add_parser("dns-settings", help="Zone DNS settings.")
    ds_sub = dns_settings.add_subparsers(dest="action", required=True)
    ds_get = ds_sub.add_parser("get")
    ds_get.add_argument("zone")
    set_func(ds_get, cmd_dns_settings_get)
    ds_patch = ds_sub.add_parser("patch")
    ds_patch.add_argument("zone")
    ds_patch.add_argument("--json", required=True)
    add_apply_flags(ds_patch)
    set_func(ds_patch, cmd_dns_settings_patch)

    zone_settings = sub.add_parser("zone-settings", help="General zone settings endpoints.")
    zs_sub = zone_settings.add_subparsers(dest="action", required=True)
    zs_list = zs_sub.add_parser("list")
    zs_list.add_argument("zone")
    set_func(zs_list, cmd_zone_settings_list)
    zs_get = zs_sub.add_parser("get")
    zs_get.add_argument("zone")
    zs_get.add_argument("setting_id")
    set_func(zs_get, cmd_zone_settings_get)
    zs_patch = zs_sub.add_parser("patch")
    zs_patch.add_argument("zone")
    zs_patch.add_argument("setting_id")
    zs_patch.add_argument("--json", required=True)
    add_apply_flags(zs_patch)
    set_func(zs_patch, cmd_zone_settings_patch)

    records = sub.add_parser("records", help="DNS record operations.", description="DNS record operations.")
    rec_sub = records.add_subparsers(dest="action", required=True)
    rec_list = rec_sub.add_parser("list")
    rec_list.add_argument("zone")
    rec_list.add_argument("--type")
    rec_list.add_argument("--name")
    rec_list.add_argument("--content")
    rec_list.add_argument("--proxied", action="store_true")
    set_func(rec_list, cmd_records_list)
    rec_find = rec_sub.add_parser("find")
    rec_find.add_argument("zone")
    rec_find.add_argument("--type")
    rec_find.add_argument("--name")
    rec_find.add_argument("--content")
    rec_find.add_argument("--proxied", action="store_true")
    set_func(rec_find, cmd_records_find)
    rec_get = rec_sub.add_parser("get")
    rec_get.add_argument("zone")
    rec_get.add_argument("record_id")
    set_func(rec_get, cmd_records_get)
    rec_create = rec_sub.add_parser("create")
    rec_create.add_argument("zone")
    add_record_body_args(rec_create)
    add_apply_flags(rec_create)
    set_func(rec_create, cmd_records_create)
    rec_create_json = rec_sub.add_parser("create-json")
    rec_create_json.add_argument("zone")
    rec_create_json.add_argument("--json", required=True)
    add_apply_flags(rec_create_json)
    set_func(rec_create_json, cmd_records_create)
    for action, method in (("patch", "PATCH"), ("put", "PUT")):
        rec_update = rec_sub.add_parser(action)
        rec_update.add_argument("zone")
        rec_update.add_argument("record_id")
        rec_update.add_argument("--json")
        add_record_body_args(rec_update, required=False)
        add_apply_flags(rec_update)
        set_func(rec_update, lambda args, m=method: cmd_records_update(args, m))
    rec_delete = rec_sub.add_parser("delete")
    rec_delete.add_argument("zone")
    rec_delete.add_argument("record_id")
    add_apply_flags(rec_delete)
    set_func(rec_delete, cmd_records_delete)
    rec_upsert = rec_sub.add_parser("upsert")
    rec_upsert.add_argument("zone")
    add_record_body_args(rec_upsert)
    add_apply_flags(rec_upsert)
    set_func(rec_upsert, cmd_records_upsert)
    rec_export = rec_sub.add_parser("export")
    rec_export.add_argument("zone")
    set_func(rec_export, cmd_records_export)
    rec_import = rec_sub.add_parser("import")
    rec_import.add_argument("zone")
    rec_import.add_argument("--file", required=True)
    add_apply_flags(rec_import)
    set_func(rec_import, cmd_records_import)
    rec_batch_plan = rec_sub.add_parser("batch-plan")
    rec_batch_plan.add_argument("zone")
    rec_batch_plan.add_argument("--json", required=True)
    set_func(rec_batch_plan, cmd_records_batch_plan)
    rec_batch_apply = rec_sub.add_parser("batch-apply")
    rec_batch_apply.add_argument("zone")
    rec_batch_apply.add_argument("--json", required=True)
    add_apply_flags(rec_batch_apply)
    set_func(rec_batch_apply, cmd_records_batch_apply)
    scan = rec_sub.add_parser("scan")
    scan_sub = scan.add_subparsers(dest="scan_action", required=True)
    for scan_action in ("trigger", "list", "review"):
        scan_parser = scan_sub.add_parser(scan_action)
        scan_parser.add_argument("zone")
        if scan_action == "review":
            scan_parser.add_argument("--json")
            add_apply_flags(scan_parser)
        set_func(scan_parser, lambda args, a=scan_action: cmd_scan(args, a))

    snapshot = sub.add_parser("snapshot", help="Create and diff DNS snapshots.")
    snap_sub = snapshot.add_subparsers(dest="action", required=True)
    snap_create = snap_sub.add_parser("create")
    snap_create.add_argument("zone")
    snap_create.add_argument("--type")
    snap_create.add_argument("--name")
    snap_create.add_argument("--content")
    snap_create.add_argument("--proxied", action="store_true")
    set_func(snap_create, cmd_snapshot_create)
    set_func(snap_sub.add_parser("create-all"), cmd_snapshot_create_all)
    snap_diff = snap_sub.add_parser("diff")
    snap_diff.add_argument("before")
    snap_diff.add_argument("after")
    set_func(snap_diff, cmd_snapshot_diff)

    plan = sub.add_parser("plan", help="Compare plans with live state.")
    plan_sub = plan.add_subparsers(dest="action", required=True)
    diff_live = plan_sub.add_parser("diff-live")
    diff_live.add_argument("zone")
    diff_live.add_argument("--plan", required=True)
    set_func(diff_live, cmd_plan_diff_live)

    return parser

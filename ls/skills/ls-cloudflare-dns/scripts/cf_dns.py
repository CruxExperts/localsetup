#!/usr/bin/env python3
"""Cloudflare DNS v4 REST helper with deterministic JSON output."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from pathlib import Path
from typing import Any

for parent in Path(__file__).resolve().parents:
    if (parent / "lib" / "deps.py").is_file():
        sys.path.insert(0, str(parent / "lib"))
        from deps import require_deps

        require_deps(["requests"])
        break

try:
    import requests
except ImportError as exc:  # pragma: no cover - environment guidance
    raise SystemExit("Missing dependency: requests. Run `uv sync --locked --no-dev` from the Localsetup source checkout.") from exc

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cf_dns_parser import build_parser as _build_parser  # noqa: E402
from cf_dns_support import (  # noqa: E402
    CONFIRM_APPLY, CONFIRM_DELETE, CONFIRM_OVERWRITE, CONFIRM_SETTINGS,
    DEFAULT_API_BASE, EXIT_AMBIGUOUS_ZONE, EXIT_API, EXIT_AUTH,
    EXIT_CONFIRMATION, HIGH_RISK_TYPES, TOKEN_ENV_VARS, ApiResponse,
    CliError, CloudflareClient, dry_run_plan, emit_json, ensure_plan_hash,
    normalize_record, output_error, output_ok, read_json_file, read_text_file,
    redact, require_apply, resolve_zone, sha256_obj, token_from_env,
    validate_record_args, write_table,
)


def client_from_args(args: argparse.Namespace) -> CloudflareClient:
    return CloudflareClient(args.api_base, timeout=args.timeout, retries=args.retries)


def cmd_auth_verify(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    response = client.request("GET", "/user/tokens/verify")
    return output_ok("auth verify", response.envelope.get("result"), rate_limit=response.rate_limit)


def cmd_permissions_summarize(args: argparse.Namespace) -> dict[str, Any]:
    token = token_from_env(required=False)
    return output_ok(
        "permissions summarize",
        {
            "token_present": bool(token),
            "token_source": next((name for name in TOKEN_ENV_VARS if os.environ.get(name)), None),
            "minimum_recommended": [
                "Zone:Zone:Read",
                "Zone:DNS:Read",
                "Zone:DNS:Edit for mutations",
                "Zone:DNS Settings:Edit only for dns-settings patch",
            ],
            "notes": [
                "Prefer a scoped API token limited to required zones.",
                "Use auth verify for live token validity.",
            ],
        },
    )


def cmd_zones_list(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    params = {key: value for key, value in {"name": args.name, "status": args.status, "account.id": args.account_id}.items() if value}
    zones, info, rate = client.paged("/zones", params)
    result = zones if args.all else zones[: args.limit]
    return output_ok("zones list", result, rate_limit=rate, extra={"result_info": info})


def cmd_zones_get(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    return output_ok("zones get", zone)


def cmd_zone_activation_check(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("PUT", f"/zones/{zone['id']}/activation_check")
    return output_ok("zones activation-check", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_zone_mutation(args: argparse.Namespace, action: str) -> dict[str, Any]:
    client = client_from_args(args)
    if action == "create":
        body = {"account": {"id": args.account_id}, "name": args.name, "type": args.type}
        endpoint = "/zones"
        method = "POST"
        phrase = CONFIRM_APPLY
        live_state = None
    else:
        zone = resolve_zone(client, args.zone)
        endpoint = f"/zones/{zone['id']}"
        method = {"edit": "PATCH", "delete": "DELETE"}[action]
        body = {"paused": args.paused, "vanity_name_servers": args.vanity_name_servers} if action == "edit" else None
        body = {k: v for k, v in (body or {}).items() if v is not None} or None
        phrase = CONFIRM_DELETE if action == "delete" else CONFIRM_APPLY
        live_state = zone
    plan = dry_run_plan(f"zones {action}", endpoint, method, body, args, live_state)
    if not args.apply:
        return output_ok(f"zones {action}", {"dry_run": True, "plan": plan})
    require_apply(args, f"zones {action}", phrase)
    ensure_plan_hash(args, plan)
    response = client.request(method, endpoint, json_body=body)
    return output_ok(f"zones {action}", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"plan_hash": plan["plan_hash"]})


def cmd_dns_settings_get(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("GET", f"/zones/{zone['id']}/dns_settings")
    return output_ok("dns-settings get", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_dns_settings_patch(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    current = client.request("GET", f"/zones/{zone['id']}/dns_settings").envelope.get("result")
    body = read_json_file(args.json)
    endpoint = f"/zones/{zone['id']}/dns_settings"
    plan = dry_run_plan("dns-settings patch", endpoint, "PATCH", body, args, current)
    if not args.apply:
        return output_ok("dns-settings patch", {"dry_run": True, "plan": plan, "current": current}, extra={"zone": zone})
    require_apply(args, "dns-settings patch", CONFIRM_SETTINGS)
    ensure_plan_hash(args, plan)
    response = client.request("PATCH", endpoint, json_body=body)
    return output_ok("dns-settings patch", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_zone_settings_list(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("GET", f"/zones/{zone['id']}/settings")
    return output_ok("zone-settings list", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_zone_settings_get(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("GET", f"/zones/{zone['id']}/settings/{args.setting_id}")
    return output_ok("zone-settings get", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_zone_settings_patch(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    current = client.request("GET", f"/zones/{zone['id']}/settings/{args.setting_id}").envelope.get("result")
    body = read_json_file(args.json)
    endpoint = f"/zones/{zone['id']}/settings/{args.setting_id}"
    plan = dry_run_plan("zone-settings patch", endpoint, "PATCH", body, args, current)
    if not args.apply:
        return output_ok("zone-settings patch", {"dry_run": True, "plan": plan, "current": current}, extra={"zone": zone})
    require_apply(args, "zone-settings patch", CONFIRM_SETTINGS)
    ensure_plan_hash(args, plan)
    response = client.request("PATCH", endpoint, json_body=body)
    return output_ok("zone-settings patch", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def records_params(args: argparse.Namespace) -> dict[str, Any]:
    return {key: value for key, value in {"type": args.type, "name": args.name, "content": args.content, "proxied": args.proxied}.items() if value is not None}


def cmd_records_list(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    records, info, rate = client.paged(f"/zones/{zone['id']}/dns_records", records_params(args))
    normalized = [normalize_record(record, zone) for record in records]
    return output_ok("records list", normalized, rate_limit=rate, extra={"zone": zone, "result_info": info})


def cmd_records_find(args: argparse.Namespace) -> dict[str, Any]:
    return cmd_records_list(args) | {"command": "records find"}


def cmd_records_get(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("GET", f"/zones/{zone['id']}/dns_records/{args.record_id}")
    return output_ok("records get", normalize_record(response.envelope.get("result") or {}, zone), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_records_create(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    body = read_json_file(args.json) if getattr(args, "json", None) else validate_record_args(args)
    endpoint = f"/zones/{zone['id']}/dns_records"
    high_risk = body.get("type", "").upper() in HIGH_RISK_TYPES
    plan = dry_run_plan("records create", endpoint, "POST", body, args, None)
    plan["high_risk"] = high_risk
    plan["plan_hash"] = sha256_obj({key: value for key, value in plan.items() if key != "plan_hash"})
    if not args.apply:
        return output_ok("records create", {"dry_run": True, "plan": plan}, extra={"zone": zone})
    require_apply(args, "records create", CONFIRM_APPLY)
    ensure_plan_hash(args, plan)
    response = client.request("POST", endpoint, json_body=body)
    return output_ok("records create", normalize_record(response.envelope.get("result") or {}, zone), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_records_update(args: argparse.Namespace, method: str) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    current = client.request("GET", f"/zones/{zone['id']}/dns_records/{args.record_id}").envelope.get("result")
    body = read_json_file(args.json) if getattr(args, "json", None) else validate_record_args(args)
    endpoint = f"/zones/{zone['id']}/dns_records/{args.record_id}"
    action = "records put" if method == "PUT" else "records patch"
    plan = dry_run_plan(action, endpoint, method, body, args, current)
    if not args.apply:
        return output_ok(action, {"dry_run": True, "plan": plan, "current": normalize_record(current or {}, zone)}, extra={"zone": zone})
    require_apply(args, action, CONFIRM_OVERWRITE if method == "PUT" else CONFIRM_APPLY)
    ensure_plan_hash(args, plan)
    response = client.request(method, endpoint, json_body=body)
    return output_ok(action, normalize_record(response.envelope.get("result") or {}, zone), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_records_delete(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    current = client.request("GET", f"/zones/{zone['id']}/dns_records/{args.record_id}").envelope.get("result")
    endpoint = f"/zones/{zone['id']}/dns_records/{args.record_id}"
    plan = dry_run_plan("records delete", endpoint, "DELETE", None, args, current)
    if not args.apply:
        return output_ok("records delete", {"dry_run": True, "plan": plan, "current": normalize_record(current or {}, zone)}, extra={"zone": zone})
    require_apply(args, "records delete", CONFIRM_DELETE)
    ensure_plan_hash(args, plan)
    response = client.request("DELETE", endpoint)
    return output_ok("records delete", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_records_upsert(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    body = validate_record_args(args)
    matches, _, _ = client.paged(f"/zones/{zone['id']}/dns_records", {"type": body["type"], "name": body["name"]})
    if len(matches) > 1:
        raise CliError("Upsert matched more than one record; use patch/put with a record ID.", EXIT_AMBIGUOUS_ZONE, {"matches": [normalize_record(item, zone) for item in matches]})
    if matches:
        args.record_id = matches[0]["id"]
        args.json = None
        return cmd_records_update(args, "PATCH") | {"command": "records upsert"}
    return cmd_records_create(args) | {"command": "records upsert"}


def cmd_records_export(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    response = client.request("GET", f"/zones/{zone['id']}/dns_records/export")
    return output_ok("records export", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone})


def cmd_records_import(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    body = read_text_file(args.file)
    endpoint = f"/zones/{zone['id']}/dns_records/import"
    plan = dry_run_plan("records import", endpoint, "POST", {"file_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest()}, args, None)
    if not args.apply:
        return output_ok("records import", {"dry_run": True, "plan": plan}, extra={"zone": zone})
    require_apply(args, "records import", CONFIRM_APPLY)
    ensure_plan_hash(args, plan)
    response = client.request("POST", endpoint, data=body, headers={"Content-Type": "text/dns"})
    return output_ok("records import", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_records_batch_plan(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    body = read_json_file(args.json)
    endpoint = f"/zones/{zone['id']}/dns_records/batch"
    plan = dry_run_plan("records batch", endpoint, "POST", body, args, None)
    return output_ok("records batch-plan", {"dry_run": True, "plan": plan}, extra={"zone": zone})


def cmd_records_batch_apply(args: argparse.Namespace) -> dict[str, Any]:
    require_apply(args, "records batch-apply", CONFIRM_APPLY)
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    body = read_json_file(args.json)
    endpoint = f"/zones/{zone['id']}/dns_records/batch"
    plan = dry_run_plan("records batch", endpoint, "POST", body, args, None)
    ensure_plan_hash(args, plan)
    response = client.request("POST", endpoint, json_body=body)
    return output_ok("records batch-apply", response.envelope.get("result"), rate_limit=response.rate_limit, extra={"zone": zone, "plan_hash": plan["plan_hash"]})


def cmd_scan(args: argparse.Namespace, action: str) -> dict[str, Any]:
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    scan_path = "review" if action in {"list", "review"} else action
    path = f"/zones/{zone['id']}/dns_records/scan/{scan_path}"
    method = "POST" if action in {"trigger", "review"} else "GET"
    body = read_json_file(args.json) if getattr(args, "json", None) else None
    if action == "review":
        plan = dry_run_plan("records scan review", path, method, body, args, None)
        if not args.apply:
            return output_ok("records scan review", {"dry_run": True, "plan": plan}, extra={"zone": zone})
        require_apply(args, "records scan review", CONFIRM_APPLY)
        ensure_plan_hash(args, plan)
    response = client.request(method, path, json_body=body)
    extra = {"zone": zone}
    if action == "review":
        extra["plan_hash"] = plan["plan_hash"]
    return output_ok(f"records scan {action}", response.envelope.get("result"), rate_limit=response.rate_limit, extra=extra)


def cmd_snapshot_create(args: argparse.Namespace) -> dict[str, Any]:
    payload = cmd_records_list(args)
    records = payload["result"]
    snapshot = {
        "zone": payload.get("zone"),
        "record_count": len(records),
        "records": records,
        "snapshot_hash": sha256_obj(records),
    }
    return output_ok("snapshot create", snapshot, rate_limit=payload.get("rate_limit"))


def cmd_snapshot_create_all(args: argparse.Namespace) -> dict[str, Any]:
    client = client_from_args(args)
    zones, _, rate = client.paged("/zones", {})
    snapshots = []
    for zone in zones:
        records, _, _ = client.paged(f"/zones/{zone['id']}/dns_records", {})
        normalized = [normalize_record(record, zone) for record in records]
        snapshots.append({"zone": zone, "record_count": len(normalized), "records": normalized, "snapshot_hash": sha256_obj(normalized)})
    return output_ok("snapshot create-all", snapshots, rate_limit=rate)


def cmd_snapshot_diff(args: argparse.Namespace) -> dict[str, Any]:
    before = read_json_file(args.before)
    after = read_json_file(args.after)
    before_records = {item["record_hash"]: item for item in before.get("records", [])}
    after_records = {item["record_hash"]: item for item in after.get("records", [])}
    return output_ok(
        "snapshot diff",
        {
            "before_hash": before.get("snapshot_hash") or sha256_obj(before),
            "after_hash": after.get("snapshot_hash") or sha256_obj(after),
            "added": [after_records[key] for key in sorted(set(after_records) - set(before_records))],
            "removed": [before_records[key] for key in sorted(set(before_records) - set(after_records))],
        },
    )


def cmd_plan_diff_live(args: argparse.Namespace) -> dict[str, Any]:
    plan = read_json_file(args.plan)
    client = client_from_args(args)
    zone = resolve_zone(client, args.zone)
    records, _, rate = client.paged(f"/zones/{zone['id']}/dns_records", {})
    live_hash = sha256_obj([normalize_record(record, zone) for record in records])
    return output_ok("plan diff-live", {"plan_hash": plan.get("plan_hash") or sha256_obj(plan), "live_hash": live_hash, "matches_live_state": plan.get("live_state_hash") == live_hash}, rate_limit=rate, extra={"zone": zone})

PARSER_COMMANDS = {
    "cmd_auth_verify": cmd_auth_verify,
    "cmd_permissions_summarize": cmd_permissions_summarize,
    "cmd_zones_list": cmd_zones_list,
    "cmd_zones_get": cmd_zones_get,
    "cmd_zone_mutation": cmd_zone_mutation,
    "cmd_zone_activation_check": cmd_zone_activation_check,
    "cmd_dns_settings_get": cmd_dns_settings_get,
    "cmd_dns_settings_patch": cmd_dns_settings_patch,
    "cmd_zone_settings_list": cmd_zone_settings_list,
    "cmd_zone_settings_get": cmd_zone_settings_get,
    "cmd_zone_settings_patch": cmd_zone_settings_patch,
    "cmd_records_list": cmd_records_list,
    "cmd_records_find": cmd_records_find,
    "cmd_records_get": cmd_records_get,
    "cmd_records_create": cmd_records_create,
    "cmd_records_update": cmd_records_update,
    "cmd_records_delete": cmd_records_delete,
    "cmd_records_upsert": cmd_records_upsert,
    "cmd_records_export": cmd_records_export,
    "cmd_records_import": cmd_records_import,
    "cmd_records_batch_plan": cmd_records_batch_plan,
    "cmd_records_batch_apply": cmd_records_batch_apply,
    "cmd_scan": cmd_scan,
    "cmd_snapshot_create": cmd_snapshot_create,
    "cmd_snapshot_create_all": cmd_snapshot_create_all,
    "cmd_snapshot_diff": cmd_snapshot_diff,
    "cmd_plan_diff_live": cmd_plan_diff_live,
}

def build_parser() -> argparse.ArgumentParser:
    return _build_parser(PARSER_COMMANDS)

def build_parser() -> argparse.ArgumentParser:
    return _build_parser(globals())


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = " ".join(part for part in [args.resource, getattr(args, "action", ""), getattr(args, "scan_action", "")] if part)
    try:
        payload = args.func(args)
        if args.output == "table" and isinstance(payload.get("result"), list):
            rows = payload["result"]
            fields = sorted({key for row in rows if isinstance(row, dict) for key in row.keys()})
            write_table(rows, fields)
        else:
            emit_json(payload)
        return 0
    except CliError as exc:
        emit_json(output_error(command, exc))
        return exc.exit_code
    except KeyboardInterrupt:
        emit_json(output_error(command, CliError("Interrupted.", 130)))
        return 130


if __name__ == "__main__":
    raise SystemExit(main())

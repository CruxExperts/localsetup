#!/usr/bin/env python3
"""Cloudflare DNS v4 REST helper with deterministic JSON output."""

from __future__ import annotations

import argparse
import csv
import hashlib
import ipaddress
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

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


DEFAULT_API_BASE = "https://api.cloudflare.com/client/v4"
TOKEN_ENV_VARS = ("CLOUDFLARE_API_TOKEN", "CF_API_TOKEN")
CONFIRM_DELETE = "confirm delete"
CONFIRM_APPLY = "confirm apply"
CONFIRM_OVERWRITE = "confirm overwrite"
CONFIRM_SETTINGS = "confirm settings"
HIGH_RISK_TYPES = {"NS", "MX", "SRV", "CAA", "DS", "DNSKEY", "SVCB", "HTTPS"}
EXIT_AUTH = 4
EXIT_CONFIRMATION = 5
EXIT_AMBIGUOUS_ZONE = 6
EXIT_API = 8


class CliError(Exception):
    def __init__(self, message: str, exit_code: int = 2, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.exit_code = exit_code
        self.details = dict(details or {})


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_obj(data: Any) -> str:
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def redact(value: Any) -> Any:
    if isinstance(value, str):
        redacted = value
        for env_name in TOKEN_ENV_VARS:
            token = os.environ.get(env_name)
            if token:
                redacted = redacted.replace(token, "<redacted>")
        if redacted.lower().startswith("bearer "):
            return "Bearer <redacted>"
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in {"authorization", "token", "api_token", "api-key", "x-auth-key"}:
                safe[key] = "<redacted>"
            else:
                safe[key] = redact(item)
        return safe
    return value


def emit_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(redact(payload), indent=2, sort_keys=True, ensure_ascii=True))


def read_json_file(path: str | None) -> Any:
    try:
        if not path or path == "-":
            return json.load(sys.stdin)
        with Path(path).expanduser().open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except json.JSONDecodeError as exc:
        raise CliError("JSON input could not be parsed.", 2, {"path": path or "-", "error": str(exc)}) from exc
    except OSError as exc:
        raise CliError("JSON input could not be read.", 2, {"path": path or "-", "error": str(exc)}) from exc


def read_text_file(path: str) -> str:
    try:
        return Path(path).expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError("Text input could not be read.", 2, {"path": path, "error": str(exc)}) from exc


def write_table(rows: list[Mapping[str, Any]], fields: list[str]) -> None:
    writer = csv.DictWriter(sys.stdout, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})


def token_from_env(required: bool = True) -> str | None:
    for name in TOKEN_ENV_VARS:
        token = os.environ.get(name)
        if token:
            return token
    if required:
        raise CliError(
            "Cloudflare API token missing. Set CLOUDFLARE_API_TOKEN or CF_API_TOKEN.",
            EXIT_AUTH,
            {"env": list(TOKEN_ENV_VARS)},
        )
    return None


def rate_limit_from_headers(headers: Mapping[str, str]) -> dict[str, str]:
    wanted = ("ratelimit", "ratelimit-policy", "retry-after")
    return {key: value for key, value in headers.items() if key.lower() in wanted}


@dataclass
class ApiResponse:
    status_code: int
    envelope: dict[str, Any]
    rate_limit: dict[str, str]


class CloudflareClient:
    def __init__(
        self,
        api_base: str = DEFAULT_API_BASE,
        token: str | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        session: requests.Session | None = None,
    ):
        self.api_base = api_base.rstrip("/")
        self.token = token or token_from_env(required=True)
        self.timeout = timeout
        self.retries = max(0, retries)
        self.session = session or requests.Session()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        expected: Iterable[int] = (200, 201, 202, 204),
    ) -> ApiResponse:
        url = f"{self.api_base}/{path.lstrip('/')}"
        request_headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
        if headers:
            request_headers.update(headers)

        last_response: requests.Response | None = None
        for attempt in range(self.retries + 1):
            try:
                response = self.session.request(
                    method.upper(),
                    url,
                    params=dict(params or {}),
                    json=json_body,
                    data=data,
                    headers=request_headers,
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                raise CliError(
                    "Cloudflare API request could not be completed.",
                    EXIT_API,
                    {"method": method.upper(), "path": path, "error": str(exc)},
                ) from exc
            last_response = response
            if response.status_code not in {429, 500, 502, 503, 504} or attempt >= self.retries:
                break
            retry_after = response.headers.get("retry-after")
            sleep_for = min(float(retry_after), 5.0) if retry_after and retry_after.isdigit() else min(0.25 * (attempt + 1), 1.0)
            time.sleep(sleep_for)

        assert last_response is not None
        envelope = self._envelope(last_response)
        api_response = ApiResponse(
            status_code=last_response.status_code,
            envelope=envelope,
            rate_limit=rate_limit_from_headers(last_response.headers),
        )
        if last_response.status_code not in set(expected) or envelope.get("success") is False:
            raise CliError(
                "Cloudflare API request failed.",
                EXIT_API,
                {
                    "method": method.upper(),
                    "path": path,
                    "status_code": last_response.status_code,
                    "errors": envelope.get("errors", []),
                    "messages": envelope.get("messages", []),
                    "rate_limit": api_response.rate_limit,
                },
            )
        return api_response

    @staticmethod
    def _envelope(response: requests.Response) -> dict[str, Any]:
        if response.status_code == 204 or not response.text:
            return {"success": True, "errors": [], "messages": [], "result": None}
        try:
            data = response.json()
        except ValueError:
            return {"success": False, "errors": [{"message": "Cloudflare API response was not valid JSON.", "body": response.text}], "messages": [], "result": None}
        if isinstance(data, dict) and {"success", "result"} & set(data):
            data.setdefault("errors", [])
            data.setdefault("messages", [])
            return data
        return {"success": response.ok, "errors": [], "messages": [], "result": data}

    def paged(self, path: str, params: Mapping[str, Any] | None = None) -> tuple[list[Any], dict[str, Any], dict[str, str]]:
        page = 1
        results: list[Any] = []
        final_info: dict[str, Any] = {}
        final_rate: dict[str, str] = {}
        while True:
            query = dict(params or {})
            query.setdefault("per_page", 100)
            query["page"] = page
            response = self.request("GET", path, params=query)
            result = response.envelope.get("result")
            if isinstance(result, list):
                results.extend(result)
            elif result is not None:
                results.append(result)
            final_info = dict(response.envelope.get("result_info") or {})
            final_rate = response.rate_limit
            total_pages = int(final_info.get("total_pages") or page)
            if page >= total_pages:
                break
            page += 1
        return results, final_info, final_rate


def output_ok(command: str, result: Any, *, rate_limit: Mapping[str, Any] | None = None, extra: Mapping[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ok": True,
        "command": command,
        "result": result,
        "errors": [],
        "messages": [],
        "rate_limit": dict(rate_limit or {}),
    }
    if extra:
        payload.update(extra)
    return payload


def output_error(command: str, exc: CliError) -> dict[str, Any]:
    return {
        "ok": False,
        "command": command,
        "result": None,
        "errors": [{"message": str(exc), "details": redact(exc.details)}],
        "messages": [],
        "rate_limit": dict(exc.details.get("rate_limit") or {}),
    }


def client_from_args(args: argparse.Namespace) -> CloudflareClient:
    return CloudflareClient(args.api_base, timeout=args.timeout, retries=args.retries)


def normalize_record(record: Mapping[str, Any], zone: Mapping[str, Any] | None = None) -> dict[str, Any]:
    known = {
        "id",
        "zone_id",
        "zone_name",
        "name",
        "type",
        "content",
        "proxied",
        "ttl",
        "priority",
        "comment",
        "tags",
        "settings",
        "meta",
        "created_on",
        "modified_on",
        "comment_modified_on",
        "tags_modified_on",
    }
    normalized = {key: record.get(key) for key in sorted(known) if key in record}
    if zone:
        normalized.setdefault("zone_id", zone.get("id"))
        normalized.setdefault("zone_name", zone.get("name"))
    unknown = {key: value for key, value in record.items() if key not in known}
    if unknown:
        normalized["provider_fields"] = unknown
    normalized["record_hash"] = sha256_obj({key: value for key, value in normalized.items() if key != "record_hash"})
    return normalized


def validate_record_args(args: argparse.Namespace) -> dict[str, Any]:
    if not args.type:
        raise CliError("Record type is required.")
    if not args.name or not args.content:
        raise CliError("Record name and content are required unless --json is supplied.")
    record_type = args.type.upper()
    body: dict[str, Any] = {"type": record_type, "name": args.name, "content": args.content}
    if args.ttl is not None:
        body["ttl"] = args.ttl
    if args.proxied is not None:
        body["proxied"] = args.proxied
    if args.priority is not None:
        body["priority"] = args.priority
    if args.comment is not None:
        body["comment"] = args.comment
    if args.tags:
        body["tags"] = args.tags
    if record_type in {"A", "AAAA"}:
        try:
            ipaddress.ip_address(args.content)
        except ValueError as exc:
            raise CliError(f"{record_type} record content must be an IP address.") from exc
    return body


def resolve_zone(client: CloudflareClient, zone: str) -> dict[str, Any]:
    if len(zone) >= 16 and "." not in zone:
        response = client.request("GET", f"/zones/{zone}")
        result = response.envelope.get("result")
        if not isinstance(result, dict):
            raise CliError("Zone ID lookup returned an unexpected result.", EXIT_API)
        return result
    zones, _, _ = client.paged("/zones", {"name": zone, "status": "active"})
    matches = [item for item in zones if isinstance(item, dict) and item.get("name") == zone]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        zones, _, _ = client.paged("/zones", {"name": zone})
        matches = [item for item in zones if isinstance(item, dict) and item.get("name") == zone]
        if len(matches) == 1:
            return matches[0]
    raise CliError(
        "Zone name did not resolve to exactly one visible zone.",
        EXIT_AMBIGUOUS_ZONE,
        {"zone": zone, "candidates": [{"id": item.get("id"), "name": item.get("name"), "status": item.get("status")} for item in matches]},
    )


def require_apply(args: argparse.Namespace, action: str, phrase: str) -> None:
    if not getattr(args, "apply", False):
        raise CliError(
            f"{action} requires --apply and --confirm '{phrase}'.",
            EXIT_CONFIRMATION,
            {"required_confirmation": phrase},
        )
    require_confirmation(args, action, phrase)


def require_confirmation(args: argparse.Namespace, action: str, phrase: str) -> None:
    if not getattr(args, "apply", False):
        return
    if getattr(args, "confirm", "") != phrase:
        raise CliError(
            f"{action} requires --confirm '{phrase}' when --apply is used.",
            EXIT_CONFIRMATION,
            {"required_confirmation": phrase},
        )


def dry_run_plan(action: str, endpoint: str, method: str, body: Any, args: argparse.Namespace, live_state: Any = None) -> dict[str, Any]:
    plan = {
        "action": action,
        "endpoint": endpoint,
        "method": method.upper(),
        "body": body,
        "live_state_hash": sha256_obj(live_state) if live_state is not None else None,
        "snapshot_required": bool(getattr(args, "require_snapshot", False)),
        "snapshot_waived": bool(getattr(args, "snapshot_waiver", False)),
    }
    plan["plan_hash"] = sha256_obj({key: value for key, value in plan.items() if key != "plan_hash"})
    return plan


def ensure_plan_hash(args: argparse.Namespace, plan: Mapping[str, Any]) -> None:
    expected = plan.get("plan_hash")
    supplied = getattr(args, "plan_hash", None)
    if getattr(args, "apply", False) and supplied and supplied != expected:
        raise CliError("Supplied --plan-hash does not match the canonical plan hash.", EXIT_CONFIRMATION, {"expected": expected, "supplied": supplied})
    if getattr(args, "apply", False) and not supplied and getattr(args, "require_plan_hash", True):
        raise CliError("Apply requires --plan-hash matching the dry-run plan.", EXIT_CONFIRMATION, {"expected": expected})


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


def build_parser() -> argparse.ArgumentParser:
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

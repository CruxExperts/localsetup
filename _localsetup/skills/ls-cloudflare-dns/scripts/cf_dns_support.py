"""Support helpers for the Cloudflare DNS CLI facade."""

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

import requests

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

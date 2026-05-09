"""Plan and apply helpers for OmniRoute desired-state reconciliation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .util import build_api_path, load_json, redact_payload

SERVER_MANAGED_KEYS = {
    "createdAt",
    "updatedAt",
    "lastUsedAt",
    "usage",
    "stats",
    "_id",
    "metadata",
}

RESOURCE_MAP: dict[str, dict[str, Any]] = {
    "providers": {
        "endpoint": "/api/providers",
        "identity_keys": ["id", "name"],
        "update_method": "PUT",
    },
    "provider_nodes": {
        "endpoint": "/api/provider-nodes",
        "identity_keys": ["id", "name"],
        "update_method": "PATCH",
    },
    "aliases": {
        "endpoint": "/api/models/alias",
        "identity_keys": ["id", "alias", "name"],
        "update_method": "PATCH",
        "live_key": "model_aliases",
    },
    "combos": {
        "endpoint": "/api/combos",
        "identity_keys": ["id", "name"],
        "update_method": "PATCH",
    },
    "fallback_chains": {
        "endpoint": "/api/fallback/chains",
        "identity_keys": ["id", "name"],
        "update_method": "PATCH",
    },
    "keys": {
        "endpoint": "/api/keys",
        "identity_keys": ["id", "key_id", "name"],
        "update_method": "PUT",
    },
    "policies": {
        "endpoint": "/api/policies",
        "identity_keys": ["id", "name"],
        "update_method": "PATCH",
    },
    "rate_limits": {
        "endpoint": "/api/rate-limit",
        "identity_keys": ["id", "name"],
        "update_method": "PUT",
    },
    "resilience": {
        "endpoint": "/api/resilience",
        "identity_keys": ["id", "name"],
        "update_method": "PATCH",
        "singleton": True,
    },
    "usage_budget": {
        "endpoint": "/api/usage/budget",
        "identity_keys": ["id", "owner_id", "name"],
        "update_method": "POST",
        "singleton": True,
    },
    "settings": {
        "endpoint": "/api/settings",
        "identity_keys": ["id", "name"],
        "update_method": "PUT",
        "singleton": True,
    },
}

REQUIRED_LIVE_SECTIONS = {
    "providers",
    "combos",
    "aliases",
    "keys",
    "usage_budget",
}


def load_desired_manifest(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    if not isinstance(payload, dict):
        raise ValueError("desired manifest must be a JSON object")
    return payload


def _normalize_for_diff(value: Any) -> Any:
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if key in SERVER_MANAGED_KEYS:
                continue
            normalized[key] = _normalize_for_diff(item)
        return normalized
    if isinstance(value, list):
        normalized_items = [_normalize_for_diff(item) for item in value]
        try:
            if all(isinstance(item, dict) for item in normalized_items):
                return sorted(
                    normalized_items,
                    key=lambda item: str(
                        item.get("id")
                        or item.get("name")
                        or item.get("alias")
                        or item.get("provider")
                        or ""
                    ),
                )
        except Exception:
            return normalized_items
        return normalized_items
    return value


def _resource_id(item: dict[str, Any], identity_keys: list[str]) -> str | None:
    for key in identity_keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _index_by_id(items: Any, identity_keys: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if isinstance(items, dict):
        candidates: list[Any] = []
        for key in (
            "data",
            "items",
            "providers",
            "combos",
            "chains",
            "aliases",
            "keys",
        ):
            value = items.get(key)
            if isinstance(value, list):
                candidates = value
                break
        if not candidates:
            candidates = [items]
        items = candidates

    if not isinstance(items, list):
        return out

    for item in items:
        if not isinstance(item, dict):
            continue
        rid = _resource_id(item, identity_keys)
        if rid:
            out[rid] = item
    return out


def build_plan(live: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    operations: list[dict[str, Any]] = []
    live_errors: dict[str, str] = {}

    for section in REQUIRED_LIVE_SECTIONS:
        config = RESOURCE_MAP.get(section, {})
        live_key = str(config.get("live_key", section))
        section_value = live.get(live_key)
        if isinstance(section_value, dict) and "error" in section_value:
            live_errors[section] = str(section_value["error"])

    if live_errors:
        return {
            "operations": [],
            "summary": {"create": 0, "update": 0, "delete": 0, "total": 0},
            "blocked": True,
            "errors": {
                "message": "required live snapshot sections failed",
                "sections": live_errors,
            },
        }

    for desired_key, config in RESOURCE_MAP.items():
        if desired_key not in desired:
            continue

        endpoint = str(config["endpoint"])
        identity_keys = list(config.get("identity_keys", ["id"]))
        update_method = str(config.get("update_method", "PUT"))
        singleton = bool(config.get("singleton", False))

        desired_value = desired[desired_key]
        live_key = str(config.get("live_key", desired_key))
        live_value = live.get(live_key)

        if singleton:
            if _normalize_for_diff(live_value) != _normalize_for_diff(desired_value):
                operations.append(
                    {
                        "resource": desired_key,
                        "endpoint": endpoint,
                        "action": "update",
                        "id": desired_key,
                        "payload": desired_value,
                        "destructive": False,
                        "method": update_method,
                    }
                )
            continue

        if isinstance(desired_value, list):
            desired_index = _index_by_id(desired_value, identity_keys)
            live_index = _index_by_id(live_value, identity_keys)

            for rid, d_item in desired_index.items():
                l_item = live_index.get(rid)
                if l_item is None:
                    operations.append(
                        {
                            "resource": desired_key,
                            "endpoint": endpoint,
                            "action": "create",
                            "id": rid,
                            "payload": d_item,
                            "destructive": False,
                            "method": "POST",
                        }
                    )
                    continue
                if _normalize_for_diff(l_item) != _normalize_for_diff(d_item):
                    operations.append(
                        {
                            "resource": desired_key,
                            "endpoint": endpoint,
                            "action": "update",
                            "id": rid,
                            "payload": d_item,
                            "destructive": False,
                            "method": update_method,
                        }
                    )

            for rid, l_item in live_index.items():
                if rid not in desired_index:
                    operations.append(
                        {
                            "resource": desired_key,
                            "endpoint": endpoint,
                            "action": "delete",
                            "id": rid,
                            "payload": l_item,
                            "destructive": True,
                            "method": "DELETE",
                        }
                    )
        else:
            if _normalize_for_diff(live_value) != _normalize_for_diff(desired_value):
                operations.append(
                    {
                        "resource": desired_key,
                        "endpoint": endpoint,
                        "action": "update",
                        "id": desired_key,
                        "payload": desired_value,
                        "destructive": False,
                        "method": update_method,
                    }
                )

    return {
        "operations": operations,
        "summary": render_plan_summary({"operations": operations}),
        "blocked": False,
    }


def render_plan_summary(plan: dict[str, Any]) -> dict[str, int]:
    summary = {"create": 0, "update": 0, "delete": 0, "total": 0}
    for op in plan.get("operations", []):
        action = op.get("action")
        if action in summary:
            summary[action] += 1
        summary["total"] += 1
    return summary


def apply_plan(
    client: Any,
    plan: dict[str, Any],
    *,
    allow_destructive: bool,
) -> dict[str, Any]:
    applied: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    skipped_destructive: list[dict[str, Any]] = []

    allowed_actions = {"create", "update", "delete"}

    if plan.get("blocked"):
        return {
            "ok": False,
            "applied_count": 0,
            "failed_count": 1,
            "skipped_destructive_count": 0,
            "applied": [],
            "failed": [
                {
                    "operation": {"action": "plan"},
                    "error": f"plan is blocked: {plan.get('errors', {})}",
                }
            ],
            "skipped_destructive": [],
            "status": "failed",
        }

    for op in plan.get("operations", []):
        if not isinstance(op, dict):
            failed.append(
                {"operation": {"raw": op}, "error": "operation must be an object"}
            )
            continue

        action = op.get("action")
        endpoint = op.get("endpoint")
        rid = op.get("id")
        payload = op.get("payload", {})
        destructive = bool(op.get("destructive", False))
        method = str(op.get("method", "")).upper()

        if action not in allowed_actions:
            failed.append({"operation": op, "error": f"unsupported action: {action}"})
            continue
        if not isinstance(endpoint, str) or not endpoint.startswith("/api/"):
            failed.append({"operation": op, "error": f"invalid endpoint: {endpoint}"})
            continue
        try:
            endpoint = build_api_path(endpoint)
        except ValueError as exc:
            failed.append({"operation": op, "error": str(exc)})
            continue
        if action in {"create", "update"} and not isinstance(payload, dict):
            failed.append(
                {"operation": op, "error": "payload must be object for create/update"}
            )
            continue

        if destructive and not allow_destructive:
            skipped_destructive.append(
                {
                    "operation": op,
                    "reason": "destructive operation skipped (allow_destructive=false)",
                }
            )
            continue

        try:
            if action == "create":
                result = client.create_resource(endpoint, payload)
            elif action == "update":
                target = (
                    build_api_path(endpoint, rid)
                    if rid and rid not in {"resilience", "usage_budget", "settings"}
                    else endpoint
                )
                if method == "PATCH":
                    result = client.patch(target, payload)
                elif method == "POST":
                    result = client.post(target, payload)
                else:
                    result = client.update_resource(target, payload)
            else:  # delete
                target = build_api_path(endpoint, rid) if rid else endpoint
                result = client.delete_resource(target)

            applied.append({"operation": op, "result": result})
        except Exception as exc:
            failed.append(
                {
                    "operation": op,
                    "error": f"{type(exc).__name__}: {redact_payload(str(exc))}",
                }
            )

    status = (
        "failed"
        if len(failed) > 0
        else ("partial_success" if len(skipped_destructive) > 0 else "success")
    )

    return {
        "ok": len(failed) == 0,
        "status": status,
        "applied_count": len(applied),
        "failed_count": len(failed),
        "skipped_destructive_count": len(skipped_destructive),
        "applied": applied,
        "failed": failed,
        "skipped_destructive": skipped_destructive,
    }

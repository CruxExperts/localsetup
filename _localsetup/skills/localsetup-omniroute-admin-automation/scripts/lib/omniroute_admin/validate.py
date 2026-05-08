"""Validation helpers for desired OmniRoute manifests."""

from __future__ import annotations

from typing import Any


ALLOWED_TOP_LEVEL = {
    "providers",
    "provider_nodes",
    "aliases",
    "combos",
    "fallback_chains",
    "keys",
    "policies",
    "rate_limits",
    "resilience",
    "usage_budget",
    "settings",
}


def _is_list_of_dicts(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, dict) for item in value)


def validate_desired_manifest(desired: Any) -> list[str]:
    """Validate desired manifest and return a list of issues."""
    issues: list[str] = []

    if not isinstance(desired, dict):
        return ["desired manifest must be a JSON object"]

    unknown_keys = sorted(set(desired.keys()) - ALLOWED_TOP_LEVEL)
    if unknown_keys:
        issues.append(f"unknown top-level keys: {', '.join(unknown_keys)}")

    for key in (
        "providers",
        "provider_nodes",
        "aliases",
        "combos",
        "fallback_chains",
        "keys",
        "policies",
        "rate_limits",
    ):
        if key in desired and not _is_list_of_dicts(desired[key]):
            issues.append(f"{key} must be a list of objects")

    if "resilience" in desired and not isinstance(desired["resilience"], dict):
        issues.append("resilience must be an object")

    if "usage_budget" in desired and not isinstance(desired["usage_budget"], dict):
        issues.append("usage_budget must be an object")

    if "settings" in desired and not isinstance(desired["settings"], dict):
        issues.append("settings must be an object")

    for idx, provider in enumerate(desired.get("providers", [])):
        if "id" not in provider and "name" not in provider:
            issues.append(f"providers[{idx}] must include id or name")

    for idx, combo in enumerate(desired.get("combos", [])):
        if "name" not in combo and "id" not in combo:
            issues.append(f"combos[{idx}] must include name or id")

    if "usage_budget" in desired:
        budget = desired["usage_budget"]
        if isinstance(budget, dict):
            required_budget_keys = [
                "owner_id",
                "owner_type",
                "period",
                "monthlyLimit",
                "alertThreshold",
                "enforce",
            ]
            for key in required_budget_keys:
                if key not in budget:
                    issues.append(f"usage_budget missing required key: {key}")

            threshold = budget.get("alertThreshold")
            if threshold is not None:
                try:
                    numeric = float(threshold)
                    if numeric < 0 or numeric > 1:
                        issues.append(
                            "usage_budget.alertThreshold must be between 0 and 1"
                        )
                except (TypeError, ValueError):
                    issues.append("usage_budget.alertThreshold must be numeric")

            monthly_limit = budget.get("monthlyLimit")
            if monthly_limit is not None:
                try:
                    if int(monthly_limit) <= 0:
                        issues.append(
                            "usage_budget.monthlyLimit must be a positive integer"
                        )
                except (TypeError, ValueError):
                    issues.append("usage_budget.monthlyLimit must be numeric")

            owner_type = budget.get("owner_type")
            if owner_type is not None and owner_type not in {"user", "team", "key"}:
                issues.append("usage_budget.owner_type must be one of: user, team, key")

            period = budget.get("period")
            if period is not None and period not in {"daily", "weekly", "monthly"}:
                issues.append(
                    "usage_budget.period must be one of: daily, weekly, monthly"
                )

            enforce_value = budget.get("enforce")
            if enforce_value is not None and not isinstance(enforce_value, bool):
                issues.append("usage_budget.enforce must be boolean")

    return issues

#!/usr/bin/env python3
# Purpose: Policy loading, validation, and action authorization for mail control.
# Created: 2026-03-07
# Last updated: 2026-03-07

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))
from deps import require_deps  # noqa: E402

require_deps(["yaml"])

import yaml  # noqa: E402

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from mail_utils import sanitize_text  # type: ignore
else:
    from .mail_utils import sanitize_text

POLICY_PATH_DEFAULT = Path("_localsetup/config/mail_protocol_policy.yaml")

ALL_ACTIONS: set[str] = {
    "smtp.send_message",
    "smtp.send_encrypted",
    "smtp.verify_connectivity",
    "smtp.refresh_session",
    "imap.list_mailboxes",
    "imap.query_messages",
    "imap.fetch_message_headers",
    "imap.fetch_message_body",
    "imap.fetch_attachment_metadata",
    "imap.fetch_attachment_content",
    "imap.fetch_and_decrypt",
    "imap.sync_state",
    "imap.get_capabilities",
    "imap.set_flags",
    "imap.clear_flags",
    "imap.copy_messages",
    "imap.move_messages",
    "imap.create_mailbox",
    "imap.rename_mailbox",
    "imap.delete_messages",
    "imap.expunge_mailbox",
    "imap.delete_mailbox",
    "imap.refresh_session",
    "crypto.encrypt_payload",
    "crypto.decrypt_payload",
}

WILDCARDS: dict[str, set[str]] = {
    "smtp.*": {a for a in ALL_ACTIONS if a.startswith("smtp.")},
    "imap.read.*": {
        "imap.list_mailboxes",
        "imap.query_messages",
        "imap.fetch_message_headers",
        "imap.fetch_message_body",
        "imap.fetch_attachment_metadata",
        "imap.fetch_attachment_content",
        "imap.fetch_and_decrypt",
        "imap.sync_state",
        "imap.get_capabilities",
    },
    "imap.write.*": {
        "imap.set_flags",
        "imap.clear_flags",
        "imap.copy_messages",
        "imap.move_messages",
        "imap.create_mailbox",
        "imap.rename_mailbox",
    },
    "imap.destructive.*": {
        "imap.delete_messages",
        "imap.expunge_mailbox",
        "imap.delete_mailbox",
    },
    "imap.admin.*": {"imap.refresh_session"},
    "imap.*": {a for a in ALL_ACTIONS if a.startswith("imap.")},
    "crypto.*": {a for a in ALL_ACTIONS if a.startswith("crypto.")},
}

THRESHOLD_ACTIONS: set[str] = {
    "imap.move_messages",
    "imap.delete_messages",
    "imap.expunge_mailbox",
    "imap.delete_mailbox",
}

COUNT_THRESHOLD_KEYS = {"delete_count_confirm", "move_count_confirm"}
BOOL_THRESHOLD_KEYS = {"expunge_requires_confirm", "folder_delete_requires_confirm"}
COUNT_MIN = 0
COUNT_MAX = 1_000_000


class PolicyError(RuntimeError):
    pass


class PolicyInputError(PolicyError):
    pass


@dataclass(slots=True)
class PolicyDecision:
    allowed: bool
    reason: str
    requires_confirmation: bool
    effective_allow: set[str]
    effective_deny: set[str]
    thresholds: dict[str, Any]
    constraints: dict[str, Any]


def _expand_actions(raw_values: Any) -> set[str]:
    expanded: set[str] = set()
    for item in raw_values if isinstance(raw_values, list) else []:
        action = sanitize_text(item, 128)
        if not action:
            continue
        if action in WILDCARDS:
            expanded.update(WILDCARDS[action])
            continue
        if action in ALL_ACTIONS:
            expanded.add(action)
            continue
        raise PolicyError(f"Unknown action identifier: {action}")
    return expanded


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise PolicyError(f"Policy file not found: {path}")
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        loaded = yaml.safe_load(content)
    except Exception as exc:  # noqa: BLE001
        raise PolicyError(f"Invalid policy YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise PolicyError("Policy root must be a mapping.")
    return loaded


def _validate_profile(name: str, profile: Any) -> None:
    if not isinstance(profile, dict):
        raise PolicyError(f"Profile '{name}' must be a mapping.")
    _expand_actions(profile.get("allow_actions", []))
    _expand_actions(profile.get("deny_actions", []))
    thresholds = profile.get("thresholds", {})
    if thresholds is None:
        thresholds = {}
    if not isinstance(thresholds, dict):
        raise PolicyError(f"Profile '{name}' thresholds must be a mapping.")
    constraints = profile.get("constraints", {})
    if constraints is not None and not isinstance(constraints, dict):
        raise PolicyError(f"Profile '{name}' constraints must be a mapping.")
    _validate_thresholds(thresholds, f"profile '{name}'")


def _parse_int(
    value: Any,
    field_name: str,
    min_value: int,
    max_value: int,
    error_cls: type[PolicyError],
) -> int:
    if isinstance(value, bool):
        raise error_cls(f"{field_name} must be an integer.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise error_cls(f"{field_name} must be an integer.") from exc
    if not min_value <= parsed <= max_value:
        raise error_cls(
            f"{field_name} must be between {min_value} and {max_value}."
        )
    return parsed


def _parse_bool(value: Any, field_name: str, error_cls: type[PolicyError]) -> bool:
    if isinstance(value, bool):
        return value
    raise error_cls(f"{field_name} must be boolean.")


def _validate_thresholds(thresholds: dict[str, Any], owner: str) -> dict[str, Any]:
    normalized = dict(thresholds)
    for key in COUNT_THRESHOLD_KEYS | BOOL_THRESHOLD_KEYS:
        if key not in thresholds:
            continue
        value = thresholds[key]
        field_name = f"Threshold '{key}' in {owner}"
        if key in COUNT_THRESHOLD_KEYS:
            normalized[key] = _parse_int(
                value, field_name, COUNT_MIN, COUNT_MAX, PolicyError
            )
        else:
            normalized[key] = _parse_bool(value, field_name, PolicyError)
    return normalized


def _validate_account(name: str, account: Any, profiles: dict[str, Any]) -> None:
    if not isinstance(account, dict):
        raise PolicyError(f"Account '{name}' must be a mapping.")
    profile = sanitize_text(account.get("profile"), 64)
    if profile and profile not in profiles:
        raise PolicyError(f"Account '{name}' references unknown profile: {profile}")
    _expand_actions(account.get("allow_actions", []))
    _expand_actions(account.get("deny_actions", []))
    thresholds = account.get("thresholds", {})
    if thresholds is None:
        thresholds = {}
    if not isinstance(thresholds, dict):
        raise PolicyError(f"Account '{name}' thresholds must be a mapping.")
    _validate_thresholds(thresholds, f"account '{name}'")
    constraints = account.get("constraints", {})
    if constraints is not None and not isinstance(constraints, dict):
        raise PolicyError(f"Account '{name}' constraints must be a mapping.")


def load_policy(path: Path) -> dict[str, Any]:
    policy = _load_yaml(path)
    required = {"version", "default_profile", "profiles", "accounts"}
    missing = [key for key in required if key not in policy]
    if missing:
        raise PolicyError(f"Missing required policy keys: {', '.join(missing)}")
    if not isinstance(policy["version"], int):
        raise PolicyError("Policy version must be an integer.")
    if policy["default_profile"] not in {"full", "restricted", "read_only"}:
        raise PolicyError(
            "default_profile must be one of: full, restricted, read_only."
        )
    profiles = policy.get("profiles")
    accounts = policy.get("accounts")
    if not isinstance(profiles, dict):
        raise PolicyError("profiles must be a mapping.")
    if not isinstance(accounts, dict):
        raise PolicyError("accounts must be a mapping.")
    for name, profile in profiles.items():
        _validate_profile(str(name), profile)
    if policy["default_profile"] not in profiles:
        raise PolicyError("default_profile must exist in profiles map.")
    for name, account in accounts.items():
        _validate_account(str(name), account, profiles)
    return policy


def _profile(policy: dict[str, Any], profile_name: str) -> dict[str, Any]:
    profiles = policy.get("profiles", {})
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise PolicyError(f"Unknown or invalid profile: {profile_name}")
    return profile


def _merged_thresholds(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[key] = value
    return merged


def _effective_thresholds(thresholds: dict[str, Any]) -> dict[str, Any]:
    try:
        return _validate_thresholds(thresholds, "effective policy")
    except PolicyError as exc:
        raise PolicyInputError(str(exc)) from exc


def _message_count(params: dict[str, Any], action: str) -> int:
    count_value = params.get("count")
    if count_value in (None, ""):
        uids = params.get("uids") or []
        if not isinstance(uids, list):
            raise PolicyInputError(
                f"{action} uids must be a list when count is absent."
            )
        return len(uids)
    return _parse_int(
        count_value, f"{action} count", COUNT_MIN, COUNT_MAX, PolicyInputError
    )


def _merged_constraints(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        merged[key] = value
    return merged


def evaluate_action(
    policy: dict[str, Any],
    account_id: str,
    action: str,
    params: dict[str, Any] | None = None,
    request_constraints: dict[str, Any] | None = None,
) -> PolicyDecision:
    if action not in ALL_ACTIONS:
        raise PolicyError(f"Action not in canonical catalog: {action}")
    account_map = policy.get("accounts", {})
    account_cfg = account_map.get(account_id) if isinstance(account_map, dict) else None
    profile_name = (
        sanitize_text((account_cfg or {}).get("profile"), 64)
        if isinstance(account_cfg, dict)
        else sanitize_text(policy.get("default_profile"), 64)
    )
    if not profile_name:
        profile_name = sanitize_text(policy.get("default_profile"), 64)
    profile = _profile(policy, profile_name)
    allow = _expand_actions(profile.get("allow_actions", []))
    deny = _expand_actions(profile.get("deny_actions", []))
    thresholds = (
        dict(profile.get("thresholds", {}))
        if isinstance(profile.get("thresholds"), dict)
        else {}
    )
    constraints = (
        dict(profile.get("constraints", {}))
        if isinstance(profile.get("constraints"), dict)
        else {}
    )
    if isinstance(account_cfg, dict):
        allow.update(_expand_actions(account_cfg.get("allow_actions", [])))
        deny.update(_expand_actions(account_cfg.get("deny_actions", [])))
        account_thresholds = account_cfg.get("thresholds", {})
        if isinstance(account_thresholds, dict):
            thresholds = _merged_thresholds(thresholds, account_thresholds)
        account_constraints = account_cfg.get("constraints", {})
        if isinstance(account_constraints, dict):
            constraints = _merged_constraints(constraints, account_constraints)
    if isinstance(request_constraints, dict):
        deny.update(_expand_actions(request_constraints.get("deny_actions", [])))
        req_thresholds = request_constraints.get("thresholds", {})
        if isinstance(req_thresholds, dict):
            thresholds = _merged_thresholds(thresholds, req_thresholds)
        req_constraints = request_constraints.get("constraints", {})
        if isinstance(req_constraints, dict):
            constraints = _merged_constraints(constraints, req_constraints)
    effective_allow = set(allow)
    effective_deny = set(deny)
    if action in effective_deny:
        return PolicyDecision(
            allowed=False,
            reason="policy_deny",
            requires_confirmation=False,
            effective_allow=effective_allow,
            effective_deny=effective_deny,
            thresholds=thresholds,
            constraints=constraints,
        )
    if action not in effective_allow:
        return PolicyDecision(
            allowed=False,
            reason="policy_not_allowed",
            requires_confirmation=False,
            effective_allow=effective_allow,
            effective_deny=effective_deny,
            thresholds=thresholds,
            constraints=constraints,
        )
    if action.startswith("crypto."):
        allowed_modes = constraints.get("allowed_encryption_modes")
        requested_mode = sanitize_text(
            (params or {}).get("encryption_mode"), 32
        ).lower()
        if isinstance(allowed_modes, list) and requested_mode:
            normalized = {sanitize_text(item, 32).lower() for item in allowed_modes}
            if requested_mode not in normalized:
                return PolicyDecision(
                    allowed=False,
                    reason="encryption_mode_not_allowed",
                    requires_confirmation=False,
                    effective_allow=effective_allow,
                    effective_deny=effective_deny,
                    thresholds=thresholds,
                    constraints=constraints,
                )
    p = params or {}
    requires_confirmation = False
    if action in THRESHOLD_ACTIONS:
        if action == "imap.move_messages":
            effective_thresholds = _effective_thresholds(thresholds)
            count = _message_count(p, action)
            requires_confirmation = count >= effective_thresholds.get(
                "move_count_confirm", 100
            )
        elif action == "imap.delete_messages":
            effective_thresholds = _effective_thresholds(thresholds)
            count = _message_count(p, action)
            requires_confirmation = count >= effective_thresholds.get(
                "delete_count_confirm", 50
            )
        elif action == "imap.expunge_mailbox":
            effective_thresholds = _effective_thresholds(thresholds)
            requires_confirmation = effective_thresholds.get(
                "expunge_requires_confirm", True
            )
        elif action == "imap.delete_mailbox":
            effective_thresholds = _effective_thresholds(thresholds)
            requires_confirmation = effective_thresholds.get(
                "folder_delete_requires_confirm", True
            )
    return PolicyDecision(
        allowed=True,
        reason="allowed",
        requires_confirmation=requires_confirmation,
        effective_allow=effective_allow,
        effective_deny=effective_deny,
        thresholds=thresholds,
        constraints=constraints,
    )

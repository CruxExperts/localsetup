from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .models import ClientVariant


DRIFT_SCHEMA_VERSION = 1
DRIFT_STATES: tuple[str, ...] = (
    "verified",
    "partial",
    "experimental",
    "unsupported",
    "unknown",
)
DRIFT_LIMITATION = "This audit compares declarations only; it does not prove runtime parity."

_CAPABILITY_PATHS: tuple[str, ...] = tuple(
    sorted(
        (
            "config.global.precedence_status",
            "config.global.status",
            "config.repo.precedence_status",
            "config.repo.status",
            "goal.limits.status",
            "goal.status",
            "insertion.global.status",
            "insertion.repo.status",
            "permissions.status",
            "policy.global.precedence_status",
            "policy.global.status",
            "policy.repo.precedence_status",
            "policy.repo.status",
            "research.status",
            "rollback.classification",
            "skills.global.precedence_status",
            "skills.global.status",
            "skills.repo.precedence_status",
            "skills.repo.status",
            "state.global.status",
            "state.repo.status",
            "support_status",
            "verification.classification",
        )
    )
)
_COMPATIBILITY_PATH = "compatibility.smoke_test_level"


def _value_at(data: Mapping[str, Any], path: str) -> Any:
    current: Any = data
    for part in path.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


def _research_state(variant: ClientVariant) -> str:
    value = _value_at(variant.data, "research.status")
    if value == "verified":
        return "verified"
    if value == "partial":
        return "partial"
    return "unknown"


def _evidence_state(left: ClientVariant, right: ClientVariant) -> str:
    evidence = (_research_state(left), _research_state(right))
    if "unknown" in evidence:
        return "unknown"
    if "partial" in evidence:
        return "partial"
    return "verified"


def _row_state(
    capability: str,
    left: Any,
    right: Any,
    evidence: str,
) -> str:
    values = (left, right)
    if "unsupported" in values:
        return "unsupported"
    if "experimental" in values:
        return "experimental"
    if left != right:
        return "partial"
    if left is None or left == "unverified":
        return "unknown"
    if left == "settings-only":
        return "partial"
    if capability == "research.status":
        return left if left in {"verified", "partial"} else "unknown"
    return evidence


def _capability_paths(left: ClientVariant, right: ClientVariant) -> tuple[str, ...]:
    if _value_at(left.data, "compatibility") is None and _value_at(right.data, "compatibility") is None:
        return _CAPABILITY_PATHS
    return tuple(sorted((*_CAPABILITY_PATHS, _COMPATIBILITY_PATH)))


def compare_variants(left: ClientVariant, right: ClientVariant) -> dict[str, Any]:
    """Compare the common semantic declarations for two client variants.

    Only registry status/classification values are compared. Native paths,
    commands, executable names, and ownership details are intentionally outside
    this audit's contract.
    """

    evidence = _evidence_state(left, right)
    rows: list[dict[str, Any]] = []
    for capability in _capability_paths(left, right):
        left_value = _value_at(left.data, capability)
        right_value = _value_at(right.data, capability)
        rows.append(
            {
                "capability": capability,
                "left": left_value,
                "right": right_value,
                "state": _row_state(capability, left_value, right_value, evidence),
                "matches": left_value == right_value,
            }
        )

    row_states = tuple(row["state"] for row in rows)
    if "unsupported" in row_states:
        overall_state = "unsupported"
    elif "experimental" in row_states:
        overall_state = "experimental"
    elif "partial" in row_states:
        overall_state = "partial"
    elif "unknown" in row_states:
        overall_state = "unknown"
    else:
        overall_state = "verified"

    return {
        "schema_version": DRIFT_SCHEMA_VERSION,
        "left": left.key,
        "right": right.key,
        "state_vocabulary": list(DRIFT_STATES),
        "rows": rows,
        "overall_state": overall_state,
        "mismatch_count": sum(not row["matches"] for row in rows),
        "limitation": DRIFT_LIMITATION,
    }

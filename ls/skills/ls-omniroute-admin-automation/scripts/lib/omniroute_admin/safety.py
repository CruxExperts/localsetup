"""Safety gates for destructive OmniRoute operations."""

from __future__ import annotations

from typing import Any


def plan_has_destructive(plan: dict[str, Any]) -> bool:
    operations = plan.get("operations")
    if not isinstance(operations, list):
        return False
    for op in operations:
        if isinstance(op, dict) and op.get("destructive") is True:
            return True
    return False


def require_destructive_ack(
    plan: dict[str, Any],
    confirmed: bool,
    allow_destructive: bool,
    action_name: str,
    require_confirmation: bool = True,
) -> None:
    if require_confirmation and not confirmed:
        raise ValueError(
            f"{action_name} requires explicit confirmation. Re-run with --yes after reviewing plan."
        )

    destructive = plan_has_destructive(plan)
    if destructive and not allow_destructive:
        raise ValueError(
            f"{action_name} includes destructive operations. Re-run with --allow-destructive and --yes."
        )

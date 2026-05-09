"""Consensus evaluation for boss-worker task outcomes."""

from __future__ import annotations

from typing import Any


def classify_discrepancy(
    primary: dict[str, Any], verifier: dict[str, Any]
) -> tuple[str, list[str]]:
    """Classify discrepancy severity between primary and verifier outputs."""
    discrepancies: list[str] = []

    if primary.get("status") != verifier.get("status"):
        discrepancies.append("status mismatch")
    if primary.get("exit_code") != verifier.get("exit_code"):
        discrepancies.append("exit_code mismatch")

    p_files = sorted(primary.get("files_changed", []) or [])
    v_files = sorted(verifier.get("files_changed", []) or [])
    if p_files != v_files:
        discrepancies.append("files_changed mismatch")

    p_stdout = str(primary.get("stdout", "")).strip()
    v_stdout = str(verifier.get("stdout", "")).strip()
    if p_stdout != v_stdout:
        discrepancies.append("stdout mismatch")

    if not discrepancies:
        return "low", []

    high_markers = {"exit_code mismatch", "status mismatch"}
    if any(d in high_markers for d in discrepancies):
        return "high", discrepancies

    return "medium", discrepancies


def consensus_verdict(
    primary: dict[str, Any],
    verifier: dict[str, Any],
) -> dict[str, Any]:
    severity, discrepancies = classify_discrepancy(primary, verifier)
    requires_tiebreaker = severity in {"high", "critical"}
    gate_passed = len(discrepancies) == 0

    return {
        "gate_passed": gate_passed,
        "severity": severity,
        "discrepancies": discrepancies,
        "requires_tiebreaker": requires_tiebreaker,
    }

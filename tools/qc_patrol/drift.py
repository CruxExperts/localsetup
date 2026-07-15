from __future__ import annotations

import hashlib
import json
from json import JSONDecodeError
from pathlib import Path
from typing import Any

from .schemas import DRIFT_PACKETS_SCHEMA, validate_payload


def _fingerprint(kind: str, affected_paths: list[str], facts: dict[str, Any]) -> str:
    material = json.dumps({"kind": kind, "paths": affected_paths, "facts": facts}, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def make_packet(
    *,
    kind: str,
    reason: str,
    severity_hint: str,
    affected_paths: list[str],
    facts: dict[str, Any],
    deterministic_evidence: list[Any],
    snippets: list[Any] | None = None,
    question: str,
    redaction_applied: bool = False,
) -> dict[str, Any]:
    fingerprint = _fingerprint(kind, affected_paths, facts)
    return {
        "packet_id": f"{kind}:{fingerprint[:16]}",
        "fingerprint": fingerprint,
        "kind": kind,
        "reason": reason,
        "severity_hint": severity_hint,
        "affected_paths": affected_paths,
        "facts": facts,
        "deterministic_evidence": deterministic_evidence,
        "snippets": snippets or [],
        "question": question,
        "redaction_applied": redaction_applied,
    }


def load_baseline(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") == "qc.inventory.v2":
        return payload
    if payload.get("schema_version") == "qc.ledger.v2":
        inventory = payload.get("inventory")
        return inventory if isinstance(inventory, dict) else None
    return None


def _files(inventory: dict[str, Any] | None) -> dict[str, str]:
    if not inventory:
        return {}
    return {
        str(row["path"]): str(row["hash"])
        for row in inventory.get("files", [])
        if isinstance(row, dict) and "path" in row and "hash" in row
    }


def _paths(rows: list[dict[str, Any]], key: str = "path") -> set[str]:
    return {str(row.get(key, "")) for row in rows if isinstance(row, dict) and row.get(key)}


def _surface(inventory: dict[str, Any], name: str) -> list[dict[str, Any]]:
    rows = (inventory.get("surfaces") or {}).get(name, [])
    return rows if isinstance(rows, list) else []


def build_drift_packets(current: dict[str, Any], baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    packets: list[dict[str, Any]] = []
    current_files = _files(current)
    baseline_files = _files(baseline)
    if baseline:
        added = sorted(set(current_files) - set(baseline_files))
        removed = sorted(set(baseline_files) - set(current_files))
        changed = sorted(path for path in set(current_files) & set(baseline_files) if current_files[path] != baseline_files[path])
        if added:
            packets.append(
                make_packet(
                    kind="shape.files_added",
                    reason="Tracked files were added since the baseline inventory.",
                    severity_hint="low",
                    affected_paths=added[:20],
                    facts={"added_count": len(added)},
                    deterministic_evidence=added[:50],
                    question="Do these new tracked files introduce a QC surface that needs deterministic coverage?",
                )
            )
        if removed:
            packets.append(
                make_packet(
                    kind="shape.files_removed",
                    reason="Tracked files were removed since the baseline inventory.",
                    severity_hint="low",
                    affected_paths=removed[:20],
                    facts={"removed_count": len(removed)},
                    deterministic_evidence=removed[:50],
                    question="Do these removals orphan generated docs, workflow references, or package boundaries?",
                )
            )
        changed_manifests = [path for path in changed if path in {"pyproject.toml", "uv.lock", "VERSION", "ls/config/pack.yaml"}]
        if changed_manifests:
            packets.append(
                make_packet(
                    kind="shape.manifests_changed",
                    reason="Package or registry manifests changed since the baseline.",
                    severity_hint="medium",
                    affected_paths=changed_manifests,
                    facts={"changed_count": len(changed_manifests)},
                    deterministic_evidence=changed_manifests,
                    question="Do changed manifests imply stale generated docs or new release boundaries?",
                )
            )
        baseline_workflows = _paths(_surface(baseline, "workflows")) if baseline else set()
        current_workflows = _paths(_surface(current, "workflows"))
        new_workflows = sorted(current_workflows - baseline_workflows)
        if new_workflows:
            packets.append(
                make_packet(
                    kind="shape.workflows_added",
                    reason="New GitHub workflows appeared since the baseline.",
                    severity_hint="medium",
                    affected_paths=new_workflows,
                    facts={"new_workflow_count": len(new_workflows)},
                    deterministic_evidence=[row for row in _surface(current, "workflows") if row.get("path") in new_workflows],
                    question="Should new workflows be added to QC workflow contracts, release exclusions, or permissions checks?",
                )
            )
        baseline_generated = _paths(_surface(baseline, "generated_artifacts")) if baseline else set()
        current_generated = _paths(_surface(current, "generated_artifacts"))
        new_generated = sorted(current_generated - baseline_generated)
        if new_generated:
            packets.append(
                make_packet(
                    kind="shape.generated_artifacts_added",
                    reason="New generated artifacts appeared since the baseline.",
                    severity_hint="low",
                    affected_paths=new_generated,
                    facts={"new_generated_count": len(new_generated)},
                    deterministic_evidence=[row for row in _surface(current, "generated_artifacts") if row.get("path") in new_generated],
                    question="Are these generated artifacts registered with source inputs and refresh tooling?",
                )
            )
    else:
        packets.append(
            make_packet(
                kind="shape.no_baseline",
                reason="No baseline inventory was available for this patrol run.",
                severity_hint="low",
                affected_paths=[],
                facts={"tracked_file_count": current.get("tracked_file_count", 0)},
                deterministic_evidence=[],
                question="Establish this run as the first adaptive QC baseline.",
            )
        )
    payload = {"schema_version": "qc.drift-packets.v1", "packets": packets}
    errors = validate_payload(payload, DRIFT_PACKETS_SCHEMA)
    if errors:
        raise ValueError("invalid QC drift packets: " + "; ".join(errors))
    return payload


def summarize_drift(packets_payload: dict[str, Any]) -> dict[str, Any]:
    packets = packets_payload.get("packets", [])
    return {
        "packet_count": len(packets),
        "kinds": sorted({str(packet.get("kind")) for packet in packets if isinstance(packet, dict)}),
    }

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ledger import write_json
from .llm_client import LLMClient, LLMDisabled
from .redaction import redact_text
from .review_contracts import parse_strict_json
from .schemas import AI_ADJUDICATION_SCHEMA, AI_ADJUDICATIONS_SCHEMA, validate_payload


def build_packet_prompt(packet: dict[str, Any]) -> str:
    payload = {
        "task": "Adjudicate one QC patrol packet. Decide only from the supplied deterministic packet evidence.",
        "safety_rules": [
            "Return strict JSON only.",
            "Do not ask for whole-repository context.",
            "Do not include secrets, credentials, raw endpoint URLs, or private path details beyond supplied affected_paths.",
            "Set should_create_issue true only for high-confidence, actionable findings backed by deterministic evidence.",
            "Use medium or low severity for uncertain findings; those remain artifact-only.",
        ],
        "output_schema": {
            "packet_id": "source packet id",
            "finding": "short actionable finding or empty if no finding",
            "confidence": "number from 0 to 1",
            "category": "docs|workflow_security|release|inventory|other_snake_case",
            "severity": "low|medium|high|critical",
            "affected_paths": ["path/from/repo/root"],
            "evidence": ["deterministic evidence item"],
            "is_actionable": True,
            "recommended_action": "specific maintainer action",
            "suggested_rule": None,
            "should_create_issue": False,
            "why_deterministic_checks_could_not_decide": "short reason",
        },
        "packet": packet,
    }
    return redact_text(json.dumps(payload, sort_keys=True))


def adjudicate_packets(
    packets_payload: dict[str, Any],
    client: LLMClient,
    out: Path,
    *,
    max_packets: int = 20,
) -> dict[str, Any]:
    adjudications: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    packets = packets_payload.get("packets", [])
    for packet in packets[:max_packets] if isinstance(packets, list) else []:
        packet_id = str(packet.get("packet_id", "unknown")) if isinstance(packet, dict) else "unknown"
        try:
            response = client.complete(build_packet_prompt(packet), response_schema=AI_ADJUDICATION_SCHEMA, schema_name="qc_ai_adjudication")
            adjudication = parse_strict_json(response, out / f"llm-raw-{packet_id.replace('/', '_').replace(':', '_')}.json", schema=AI_ADJUDICATION_SCHEMA)
            adjudications.append(adjudication)
        except LLMDisabled as exc:
            errors.append({"packet_id": packet_id, "error": redact_text(str(exc))})
            break
        except Exception as exc:
            errors.append({"packet_id": packet_id, "error": redact_text(str(exc))})
    payload = {"schema_version": "qc.ai-adjudication.v1", "adjudications": adjudications, "errors": errors}
    schema_errors = validate_payload(payload, AI_ADJUDICATIONS_SCHEMA)
    if schema_errors:
        raise ValueError("invalid QC AI adjudications: " + "; ".join(schema_errors))
    if errors:
        write_json(out / "llm-error.json", {"errors": errors})
    return payload


def rule_suggestions_from_adjudications(adjudications_payload: dict[str, Any]) -> dict[str, Any]:
    suggestions: list[dict[str, Any]] = []
    for item in adjudications_payload.get("adjudications", []):
        suggested = item.get("suggested_rule") if isinstance(item, dict) else None
        if not isinstance(suggested, dict):
            continue
        suggestions.append(
            {
                "rule_id": str(suggested.get("rule_id") or f"candidate.{item.get('packet_id', 'unknown')}"),
                "source_packet_id": str(item.get("packet_id", "")),
                "type": str(suggested.get("type", "deterministic_candidate")),
                "scope": str(suggested.get("scope", "")),
                "source_of_truth": str(suggested.get("source_of_truth", "")),
                "ignore_contexts": [str(value) for value in suggested.get("ignore_contexts", [])] if isinstance(suggested.get("ignore_contexts", []), list) else [],
                "rationale": str(suggested.get("rationale", item.get("finding", ""))),
                "confidence": float(item.get("confidence", 0)),
                "example_evidence": item.get("evidence", []),
                "promotion_state": "candidate",
            }
        )
    return {"schema_version": "qc.rule-suggestions.v1", "suggestions": suggestions}


def ai_findings_from_adjudications(adjudications_payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in adjudications_payload.get("adjudications", []):
        if not isinstance(item, dict) or not item.get("finding"):
            continue
        findings.append(
            {
                "category": item["category"],
                "severity": item["severity"],
                "title": str(item["finding"])[:140],
                "body": f"{item['finding']}\n\nRecommended action: {item['recommended_action']}",
                "affected_paths": item["affected_paths"],
                "region": str(item.get("packet_id", "")),
                "check_type": "ai_packet_adjudication",
                "remediation": item["recommended_action"],
                "confidence": item["confidence"],
                "is_actionable": item["is_actionable"],
                "should_create_issue": item["should_create_issue"],
                "evidence": item["evidence"],
            }
        )
    return findings

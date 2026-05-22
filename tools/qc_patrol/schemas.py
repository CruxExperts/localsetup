from __future__ import annotations

from typing import Any

from jsonschema import Draft202012Validator


FINDING_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["category", "severity", "title", "body", "affected_paths"],
    "additionalProperties": False,
    "properties": {
        "category": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "title": {"type": "string", "minLength": 1, "maxLength": 140},
        "body": {"type": "string", "minLength": 1, "maxLength": 6000},
        "affected_paths": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "region": {"type": "string", "maxLength": 200},
        "check_type": {"type": "string", "maxLength": 80},
        "remediation": {"type": "string", "maxLength": 2000},
    },
}

LEDGER_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "command", "ok", "findings"],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"const": "qc.ledger.v1"},
        "command": {"type": "string"},
        "ok": {"type": "boolean"},
        "findings": {"type": "array", "items": FINDING_SCHEMA},
    },
}

INVENTORY_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "created_at_unix", "head_sha", "tracked_file_count", "files", "surfaces", "version_truth"],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"const": "qc.inventory.v2"},
        "created_at_unix": {"type": "integer"},
        "head_sha": {"type": "string"},
        "tracked_file_count": {"type": "integer", "minimum": 0},
        "files": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["path", "hash"],
                "additionalProperties": True,
                "properties": {"path": {"type": "string"}, "hash": {"type": "string"}},
            },
        },
        "surfaces": {"type": "object"},
        "version_truth": {"type": "object"},
    },
}

DRIFT_PACKETS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "packets"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": "qc.drift-packets.v1"},
        "packets": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "packet_id",
                    "fingerprint",
                    "kind",
                    "reason",
                    "severity_hint",
                    "affected_paths",
                    "facts",
                    "deterministic_evidence",
                    "snippets",
                    "question",
                    "redaction_applied",
                ],
                "additionalProperties": True,
                "properties": {
                    "packet_id": {"type": "string"},
                    "fingerprint": {"type": "string"},
                    "kind": {"type": "string"},
                    "reason": {"type": "string"},
                    "severity_hint": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
                    "affected_paths": {"type": "array", "items": {"type": "string"}},
                    "facts": {"type": "object"},
                    "deterministic_evidence": {"type": "array"},
                    "snippets": {"type": "array"},
                    "question": {"type": "string"},
                    "redaction_applied": {"type": "boolean"},
                },
            },
        },
    },
}

AI_ADJUDICATION_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": [
        "packet_id",
        "finding",
        "confidence",
        "category",
        "severity",
        "affected_paths",
        "evidence",
        "is_actionable",
        "recommended_action",
        "suggested_rule",
        "should_create_issue",
        "why_deterministic_checks_could_not_decide",
    ],
    "additionalProperties": False,
    "properties": {
        "packet_id": {"type": "string"},
        "finding": {"type": "string", "maxLength": 6000},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "category": {"type": "string", "pattern": "^[a-z][a-z0-9_-]*$"},
        "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
        "affected_paths": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "evidence": {"type": "array", "items": {"type": "string"}, "maxItems": 20},
        "is_actionable": {"type": "boolean"},
        "recommended_action": {"type": "string", "maxLength": 2000},
        "suggested_rule": {"type": ["object", "null"]},
        "should_create_issue": {"type": "boolean"},
        "why_deterministic_checks_could_not_decide": {"type": "string", "maxLength": 2000},
    },
}

AI_ADJUDICATIONS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "adjudications"],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"const": "qc.ai-adjudication.v1"},
        "adjudications": {"type": "array", "items": AI_ADJUDICATION_SCHEMA},
    },
}

RULE_SUGGESTIONS_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "suggestions"],
    "additionalProperties": False,
    "properties": {
        "schema_version": {"const": "qc.rule-suggestions.v1"},
        "suggestions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["rule_id", "source_packet_id", "type", "scope", "rationale", "confidence", "promotion_state"],
                "additionalProperties": True,
                "properties": {
                    "rule_id": {"type": "string"},
                    "source_packet_id": {"type": "string"},
                    "type": {"type": "string"},
                    "scope": {"type": "string"},
                    "source_of_truth": {"type": "string"},
                    "ignore_contexts": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "example_evidence": {"type": "array"},
                    "promotion_state": {"type": "string"},
                },
            },
        },
    },
}

LEDGER_V2_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["schema_version", "command", "ok", "created_at_unix", "head_sha", "deterministic_findings", "ai_findings", "artifacts", "ai_mode"],
    "additionalProperties": True,
    "properties": {
        "schema_version": {"const": "qc.ledger.v2"},
        "command": {"type": "string"},
        "ok": {"type": "boolean"},
        "created_at_unix": {"type": "integer"},
        "head_sha": {"type": "string"},
        "deterministic_findings": {"type": "array", "items": FINDING_SCHEMA},
        "ai_findings": {"type": "array"},
        "artifacts": {"type": "object"},
        "ai_mode": {"type": "string", "enum": ["off", "packets"]},
    },
}

LLM_REVIEW_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["findings"],
    "additionalProperties": False,
    "properties": {"findings": {"type": "array", "items": FINDING_SCHEMA, "maxItems": 20}},
}


def validate_payload(payload: Any, schema: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(schema)
    return [error.message for error in sorted(validator.iter_errors(payload), key=lambda e: list(e.path))]

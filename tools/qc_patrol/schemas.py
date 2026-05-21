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

"""Bounded JSON schemas used by the protected release-document completion calls."""
from __future__ import annotations

from typing import Any


MAX_RESPONSE_BYTES = 1_000_000
MAX_EVIDENCE_ITEMS = 24
MAX_FACTS_PER_CALL = 8
MAX_MAPPING_FACTS = 24
CHUNK_BYTES = 12_000

EVIDENCE: dict[str, Any] = {
    "type": "array", "minItems": 1, "maxItems": MAX_EVIDENCE_ITEMS,
    "items": {"type": "string", "minLength": 1, "maxLength": 300},
}
COVERAGE: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["path", "chunk", "disposition", "evidence"],
    "properties": {
        "path": {"type": "string"}, "chunk": {"type": "integer", "minimum": 0},
        "disposition": {"type": "string", "enum": ["no_change", "update_recommended", "needs_follow_up"]},
        "evidence": EVIDENCE,
    },
}
EDIT: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["path", "content", "evidence"],
    "properties": {
        "path": {"type": "string"}, "content": {"type": "string", "minLength": 1, "maxLength": 192_000},
        "evidence": EVIDENCE,
    },
}
AUDIT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["coverage", "edits"],
    "properties": {"coverage": {"type": "array", "items": COVERAGE}, "edits": {"type": "array", "items": EDIT}},
}
FACT: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["path", "chunk", "text", "evidence"],
    "properties": {
        "path": {"type": "string"}, "chunk": {"type": "integer", "minimum": 0},
        "text": {"type": "string", "minLength": 1, "maxLength": 800}, "evidence": EVIDENCE,
    },
}
FACT_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["facts"],
    "properties": {"facts": {"type": "array", "minItems": 1, "maxItems": MAX_FACTS_PER_CALL, "items": FACT}},
}
SUMMARY_SCHEMA: dict[str, Any] = {**FACT_SCHEMA, "properties": {
    "facts": {**FACT_SCHEMA["properties"]["facts"], "maxItems": 1},
}}
MAP_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["mappings"],
    "properties": {"mappings": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["path", "chunk", "source"],
        "properties": {"path": {"type": "string"}, "chunk": {"type": "integer", "minimum": 0}, "source": {
            "type": "array", "maxItems": 3, "items": {"type": "object", "additionalProperties": False,
                "required": ["path", "chunk"], "properties": {"path": {"type": "string"}, "chunk": {"type": "integer", "minimum": 0}}},
        }},
    }}},
}
RECORD: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "version", "source_commit", "baseline_tag", "summary", "highlights", "compatibility", "update", "verification"],
    "properties": {
        "schema_version": {"const": 1},
        "version": {"type": "string", "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$"},
        "source_commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
        "baseline_tag": {"type": "string", "pattern": "^v[0-9]+\\.[0-9]+\\.[0-9]+$"},
        "summary": {"type": "string", "minLength": 1, "maxLength": 3000},
        "highlights": {"type": "array", "minItems": 1, "maxItems": 32, "items": {
            "type": "object", "additionalProperties": False, "required": ["text", "evidence"],
            "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 1000}, "evidence": EVIDENCE},
        }},
        "compatibility": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"type": "string", "minLength": 1, "maxLength": 2000}},
        "update": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"type": "string", "minLength": 1, "maxLength": 2000}},
        "verification": {"type": "array", "minItems": 1, "maxItems": 64, "items": {"type": "string", "minLength": 1, "maxLength": 2000}},
    },
}
RECORD_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": ["record"], "properties": {"record": RECORD}}
CLAIM_MAP_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["mappings"],
    "properties": {"mappings": {"type": "array", "minItems": 1, "maxItems": 1, "items": {
        "type": "object", "additionalProperties": False, "required": ["claim", "source"],
        "properties": {"claim": {"type": "string"}, "source": {"type": "array", "minItems": 0, "maxItems": 3,
            "items": {"type": "object", "additionalProperties": False, "required": ["path", "chunk"],
                "properties": {"path": {"type": "string"}, "chunk": {"type": "integer", "minimum": 0}}}}},
    }}},
}
REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False, "required": ["accepted", "findings", "evidence"],
    "properties": {"accepted": {"type": "boolean"}, "findings": {"type": "array", "maxItems": 20, "items": {
        "type": "object", "additionalProperties": False, "required": ["title", "body"],
        "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    }}, "evidence": EVIDENCE},
}

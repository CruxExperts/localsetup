from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def validate_json_schema(data: dict[str, Any], schema_path: Path, *, label: str) -> list[str]:
    if not schema_path.exists():
        return []
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        return [f"jsonschema is required to validate {label}"]
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda error: list(error.path))
    issues: list[str] = []
    for error in errors:
        dotted = ".".join(str(part) for part in error.path) or "<root>"
        issues.append(f"{label} schema validation failed at {dotted}: {error.message}")
    return issues

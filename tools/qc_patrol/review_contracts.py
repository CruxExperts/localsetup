from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ledger import write_json
from .schemas import LLM_REVIEW_SCHEMA, validate_payload


def _loads_strict_or_repeated_identical(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("LLM response JSON must be an object")
        return payload
    except json.JSONDecodeError:
        decoder = json.JSONDecoder()
        values: list[Any] = []
        index = 0
        while index < len(text):
            while index < len(text) and text[index].isspace():
                index += 1
            if index >= len(text):
                break
            value, index = decoder.raw_decode(text, index)
            values.append(value)
        if values and all(value == values[0] for value in values):
            if not isinstance(values[0], dict):
                raise ValueError("LLM response JSON must be an object")
            return values[0]
        raise


def parse_strict_json(text: str, raw_out: Path | None = None, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        payload = _loads_strict_or_repeated_identical(text)
    except (json.JSONDecodeError, ValueError) as exc:
        if raw_out:
            write_json(raw_out, {"raw_response": text})
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc
    errors = validate_payload(payload, schema or LLM_REVIEW_SCHEMA)
    if errors:
        if raw_out:
            write_json(raw_out, {"raw_response": text, "schema_errors": errors})
        raise ValueError("LLM response failed schema validation: " + "; ".join(errors))
    return payload

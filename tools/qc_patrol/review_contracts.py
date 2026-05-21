from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ledger import write_json
from .schemas import LLM_REVIEW_SCHEMA, validate_payload


def parse_strict_json(text: str, raw_out: Path | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        if raw_out:
            write_json(raw_out, {"raw_response": text})
        raise ValueError(f"LLM response was not valid JSON: {exc}") from exc
    errors = validate_payload(payload, LLM_REVIEW_SCHEMA)
    if errors:
        if raw_out:
            write_json(raw_out, {"raw_response": text, "schema_errors": errors})
        raise ValueError("LLM response failed schema validation: " + "; ".join(errors))
    return payload

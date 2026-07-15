from __future__ import annotations

import json
from typing import Any

from .models import ContextIndexError


def json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def error_payload(command: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ContextIndexError):
        return {
            "ok": False,
            "command": command,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "recommended_action": exc.recommended_action,
            },
        }
    return {
        "ok": False,
        "command": command,
        "error": {
            "code": type(exc).__name__,
            "message": str(exc),
            "recommended_action": "Inspect the command arguments and context-index configuration.",
        },
    }

"""Utility helpers for Kilo boss orchestrator."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_ROOT = Path(".kilo/state/orchestrator")
SENSITIVE_KEY_TOKENS = {
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "authorization",
    "cookie",
    "access_key",
    "private_key",
}
REDACTED = "***REDACTED***"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_state_dirs(root: Path = STATE_ROOT) -> None:
    for rel in ["tasks", "results", "leases", "heartbeats", "consensus", "sessions"]:
        (root / rel).mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True, exist_ok=True)


def sanitize_text(value: object, limit: int = 2000) -> str:
    text = str(value)
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else "?" for ch in text)
    cleaned = " ".join(cleaned.split())
    return cleaned[:limit] if len(cleaned) > limit else cleaned


def sanitize_path(raw: str) -> Path:
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError("path must be non-empty string")
    if "\x00" in raw:
        raise ValueError("path contains null byte")
    return Path(raw).expanduser()


def _redact_string(value: str) -> str:
    redacted = value
    patterns = [
        (r"sk-[A-Za-z0-9._-]+", REDACTED),
        (r"Bearer\s+[A-Za-z0-9._:-]+", f"Bearer {REDACTED}"),
        (r"(api[_-]?key\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
        (r"(token\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
        (r"(authorization\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
    ]
    for pattern, repl in patterns:
        redacted = re.sub(pattern, repl, redacted, flags=re.IGNORECASE)
    return redacted


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            if any(token in key_text for token in SENSITIVE_KEY_TOKENS):
                out[str(key)] = REDACTED
            else:
                out[str(key)] = redact_payload(item)
        return out
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"unable to load JSON {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_payload(payload)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_payload(payload)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(safe, sort_keys=True) + "\n")


def load_yaml(path: Path) -> Any:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"unable to load YAML {path}: {exc}") from exc


def write_yaml(path: Path, payload: Any) -> None:
    import yaml

    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_payload(payload)
    path.write_text(yaml.safe_dump(safe, sort_keys=False), encoding="utf-8")

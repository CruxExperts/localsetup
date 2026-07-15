"""Utility helpers for OmniRoute admin tooling."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

MAX_TEXT = 2000
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
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
SAFE_ENV_KEYS = {
    "api_key_env",
    "base_url_env",
    "management_cookie_env",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sanitize_text(value: object, limit: int = MAX_TEXT) -> str:
    text = str(value)
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else "?" for ch in text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


def sanitize_path(raw: str) -> Path:
    if not isinstance(raw, str) or raw.strip() == "":
        raise ValueError("path must be a non-empty string")
    path = Path(raw).expanduser()
    if "\x00" in raw:
        raise ValueError("path contains null byte")
    return path


def encode_path_segment(raw: object, label: str = "identifier") -> str:
    """Validate and percent-encode one user-controlled URL path segment."""
    if not isinstance(raw, str):
        raise ValueError(f"{label} must be a string")
    value = raw.strip()
    if not value:
        raise ValueError(f"{label} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{label} contains null byte")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{label} contains control characters")
    return quote(value, safe="")


def build_api_path(endpoint: object, identifier: object | None = None) -> str:
    """Validate a repo-known API endpoint and append an encoded identifier."""
    if not isinstance(endpoint, str):
        raise ValueError("endpoint must be a string")
    parts = urlsplit(endpoint)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise ValueError(
            "endpoint must be a relative API path without query or fragment"
        )
    path = parts.path
    if not path.startswith("/api/"):
        raise ValueError("endpoint must start with /api/")
    if "\x00" in path or any(ord(ch) < 32 or ord(ch) == 127 for ch in path):
        raise ValueError("endpoint contains control characters")
    if identifier is None:
        return path
    return f"{path.rstrip('/')}/{encode_path_segment(identifier)}"


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_json(path: Path) -> Any:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"unable to read JSON file {path}: {exc}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def print_json(payload: Any) -> None:
    print(json.dumps(redact_payload(payload), indent=2, sort_keys=True))


def load_text_env(env_name: str | None) -> str | None:
    if not env_name:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ValueError(
            f"invalid environment variable name: {sanitize_text(env_name)}"
        )
    value = os.environ.get(env_name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _redact_string(value: str) -> str:
    """Redact common inline secret patterns from arbitrary strings."""
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
    """Recursively redact sensitive values in nested payloads."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower().replace("-", "_")
            if key_text in SAFE_ENV_KEYS and isinstance(item, str) and ENV_NAME_RE.fullmatch(item):
                redacted[str(key)] = redact_payload(item)
            elif any(token in key_text for token in SENSITIVE_KEY_TOKENS):
                redacted[str(key)] = REDACTED
            elif key_text.endswith("_env"):
                redacted[str(key)] = (
                    redact_payload(item)
                    if isinstance(item, str) and ENV_NAME_RE.fullmatch(item)
                    else REDACTED
                )
            else:
                redacted[str(key)] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def error(message: str, details: str | None = None) -> None:
    base = f"[omniroute_admin ERROR] {sanitize_text(message)}"
    if details:
        safe_details = sanitize_text(str(redact_payload(details)))
        base = f"{base} | {safe_details}"
    print(base, file=sys.stderr)

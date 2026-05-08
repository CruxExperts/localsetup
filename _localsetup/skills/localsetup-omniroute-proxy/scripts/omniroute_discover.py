#!/usr/bin/env python3
"""Read-only OmniRoute discovery probe.

Usage:
    python3 omniroute_discover.py --base-url http://localhost:20128 --markdown
    OMNIROUTE_API_KEY=... python3 omniroute_discover.py --api-key-env OMNIROUTE_API_KEY --json

The script reads credentials only from an environment variable, probes safe
read-only endpoints, and reports per-endpoint status. It does not mutate
OmniRoute configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


DEFAULT_BASE_URL = "http://localhost:20128"
MAX_BODY_BYTES = 2_000_000
MAX_TEXT = 500


@dataclass(frozen=True)
class ProbeTarget:
    name: str
    path: str


TARGETS = [
    ProbeTarget("health", "/api/monitoring/health"),
    ProbeTarget("model_catalog", "/api/models/catalog"),
    ProbeTarget("openai_models", "/v1/models"),
    ProbeTarget("a2a_agent_card", "/.well-known/agent.json"),
    ProbeTarget("rate_limits", "/api/rate-limits"),
    ProbeTarget("resilience", "/api/resilience"),
    ProbeTarget("usage_budget", "/api/usage/budget"),
    ProbeTarget("telemetry_summary", "/api/telemetry/summary"),
]


def sanitize_text(value: object, limit: int = MAX_TEXT) -> str:
    """Return printable text with control characters stripped."""
    text = str(value)
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else "?" for ch in text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


def parse_base_url(raw_url: str) -> str:
    """Validate and normalize an HTTP(S) base URL."""
    parsed = urllib.parse.urlparse(raw_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("base URL must use http or https")
    if not parsed.netloc:
        raise ValueError("base URL must include a host")
    if parsed.username or parsed.password:
        raise ValueError("base URL must not include credentials")
    normalized = urllib.parse.urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", "")
    )
    return normalized or DEFAULT_BASE_URL


def join_url(base_url: str, path: str) -> str:
    """Join a normalized base URL and absolute endpoint path."""
    return f"{base_url}{path}"


def load_api_key(env_name: str | None) -> str | None:
    """Read API key from an environment variable name only."""
    if not env_name:
        return None
    if not env_name.replace("_", "").isalnum():
        raise ValueError(
            "api key environment variable name contains invalid characters"
        )
    value = os.environ.get(env_name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def fetch_json(url: str, api_key: str | None, timeout: float) -> dict[str, Any]:
    """Fetch one endpoint and return a normalized probe result."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    started = time.monotonic()

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type", "")
            body = response.read(MAX_BODY_BYTES + 1)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if len(body) > MAX_BODY_BYTES:
                return {
                    "ok": False,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "error": "response exceeded size limit",
                }
            decoded = body.decode("utf-8", errors="replace")
            try:
                payload = json.loads(decoded) if decoded else None
            except json.JSONDecodeError as exc:
                return {
                    "ok": False,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "content_type": sanitize_text(content_type),
                    "error": f"invalid JSON: {exc.msg}",
                    "sample": sanitize_text(decoded),
                }
            return {
                "ok": 200 <= int(status) < 300,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "content_type": sanitize_text(content_type),
                "summary": summarize_payload(payload),
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        body = exc.read(2048).decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": exc.code,
            "elapsed_ms": elapsed_ms,
            "error": sanitize_text(exc.reason),
            "sample": sanitize_text(body),
        }
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {sanitize_text(exc)}",
        }


def summarize_payload(payload: Any) -> dict[str, Any]:
    """Summarize a JSON payload without dumping large or sensitive data."""
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())[:20]
        summary: dict[str, Any] = {"type": "object", "keys": keys}
        for candidate in ("data", "models", "providers", "items"):
            value = payload.get(candidate)
            if isinstance(value, list):
                summary[f"{candidate}_count"] = len(value)
        return summary
    if isinstance(payload, list):
        return {"type": "array", "count": len(payload)}
    if payload is None:
        return {"type": "null"}
    return {"type": type(payload).__name__, "value": sanitize_text(payload)}


def run_probe(base_url: str, api_key: str | None, timeout: float) -> dict[str, Any]:
    """Run all read-only probes."""
    endpoints = {}
    for target in TARGETS:
        endpoints[target.name] = fetch_json(
            join_url(base_url, target.path), api_key, timeout
        )
    return {
        "base_url": base_url,
        "authenticated": bool(api_key),
        "endpoints": endpoints,
    }


def render_markdown(report: dict[str, Any]) -> str:
    """Render a compact Markdown report."""
    lines = [
        "# OmniRoute discovery report",
        "",
        f"Base URL: `{report['base_url']}`",
        f"Authenticated: `{'yes' if report['authenticated'] else 'no'}`",
        "",
        "| Endpoint | OK | Status | Time | Summary |",
        "|---|---:|---:|---:|---|",
    ]
    endpoints = report.get("endpoints", {})
    if not isinstance(endpoints, dict):
        return "# OmniRoute discovery report\n\nInvalid report shape."
    for name, result in endpoints.items():
        if not isinstance(result, dict):
            continue
        ok = "yes" if result.get("ok") else "no"
        status = result.get("status") if result.get("status") is not None else "n/a"
        elapsed = result.get("elapsed_ms", "n/a")
        summary = (
            result.get("summary") if result.get("ok") else result.get("error", "failed")
        )
        lines.append(
            f"| `{sanitize_text(name)}` | {ok} | {status} | {elapsed} ms | {sanitize_text(summary)} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- This script only uses read-only endpoints.",
            "- Missing endpoints may indicate server version differences, disabled features, or auth requirements.",
            "- Capability and rate-limit fields should be treated as partial unless confirmed by the target server.",
        ]
    )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(description="Read-only OmniRoute discovery probe")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("OMNIROUTE_BASE_URL", DEFAULT_BASE_URL),
        help="OmniRoute base URL, default: OMNIROUTE_BASE_URL or http://localhost:20128",
    )
    parser.add_argument(
        "--api-key-env",
        default="OMNIROUTE_API_KEY",
        help="Environment variable containing bearer token; use empty string to disable",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Per-endpoint timeout in seconds, default: 5",
    )
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", help="Emit JSON report")
    output.add_argument("--markdown", action="store_true", help="Emit Markdown report")
    return parser


def main() -> int:
    """CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.timeout <= 0 or args.timeout > 60:
            raise ValueError(
                "timeout must be greater than 0 and no more than 60 seconds"
            )
        base_url = parse_base_url(args.base_url)
        api_key_env = args.api_key_env.strip() or None
        api_key = load_api_key(api_key_env)
        report = run_probe(base_url, api_key, args.timeout)
    except ValueError as exc:
        print(f"error: {sanitize_text(exc)}", file=sys.stderr)
        return 2

    if args.markdown:
        print(render_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

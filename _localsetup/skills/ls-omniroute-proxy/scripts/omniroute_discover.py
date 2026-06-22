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
import re
import shlex
import sys
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
LIB_DIR = SCRIPT_DIR.parents[2] / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from deps import require_deps  # noqa: E402

require_deps(["requests"])
import requests  # noqa: E402


DEFAULT_BASE_URL = "http://localhost:20128"
MAX_BODY_BYTES = 2_000_000
MAX_TEXT = 500
REDACTED = "***REDACTED***"
SECRET_PATTERNS = (
    (r"sk-[A-Za-z0-9._-]+", REDACTED),
    (r"Bearer\s+[A-Za-z0-9._:-]+", f"Bearer {REDACTED}"),
    (r"(api[_-]?key\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
    (r"(token\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
    (r"(authorization\s*[=:]\s*)([^\s,;]+)", rf"\1{REDACTED}"),
)


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

ACCESS_TARGETS = {
    "runtime": [ProbeTarget("openai_models", "/v1/models")],
    "read": [
        ProbeTarget("health", "/api/monitoring/health"),
        ProbeTarget("model_catalog", "/api/models/catalog"),
    ],
    "write": [
        ProbeTarget("health", "/api/monitoring/health"),
        ProbeTarget("model_catalog", "/api/models/catalog"),
        ProbeTarget("settings_read", "/api/settings"),
    ],
    "admin": [
        ProbeTarget("health", "/api/monitoring/health"),
        ProbeTarget("keys_read", "/api/keys"),
        ProbeTarget("settings_read", "/api/settings"),
    ],
}


def sanitize_text(value: object, limit: int = MAX_TEXT) -> str:
    """Return printable text with control characters stripped."""
    text = redact_text(str(value))
    cleaned = "".join(ch if ch.isprintable() or ch in "\n\t" else "?" for ch in text)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > limit:
        return cleaned[: limit - 3] + "..."
    return cleaned


def redact_text(value: str) -> str:
    redacted = value
    for pattern, replacement in SECRET_PATTERNS:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE)
    return redacted


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


def endpoint_hint(url: str) -> str:
    """Return an operator-facing hint for endpoint failures."""
    parsed = urllib.parse.urlparse(url)
    path = parsed.path or "/"
    if path == "/api/monitoring/health":
        return "Confirm the OmniRoute proxy is running and reachable at --base-url."
    if path.startswith("/v1") or path.startswith("/v1beta") or path == "/api/tags":
        return "Confirm this compatibility route is enabled on the target OmniRoute proxy."
    if path == "/.well-known/agent.json":
        return "A2A discovery may be disabled or unsupported on this proxy version."
    if path.startswith("/api/"):
        return (
            "Confirm the endpoint exists on this OmniRoute version "
            "and check whether bearer auth is required."
        )
    return "Confirm the endpoint path is supported by the target OmniRoute proxy."


def load_api_key(env_name: str | None) -> str | None:
    """Read API key from an environment variable name only."""
    if not env_name:
        return None
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env_name):
        raise ValueError(
            "api key environment variable name contains invalid characters"
        )
    value = os.environ.get(env_name)
    if value is None or value.strip() == "":
        return None
    return value.strip()


def fetch_json(
    session: requests.Session, url: str, api_key: str | None, timeout: float
) -> dict[str, Any]:
    """Fetch one endpoint and return a normalized probe result."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    started = time.monotonic()

    try:
        response = session.get(url, headers=headers, timeout=timeout, stream=True)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        status = response.status_code
        content_type = response.headers.get("Content-Type", "")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_BODY_BYTES:
                response.close()
                return {
                    "ok": False,
                    "status": status,
                    "elapsed_ms": elapsed_ms,
                    "url": url,
                    "error": f"response exceeded size limit of {MAX_BODY_BYTES} bytes",
                    "hint": (
                        "Use a narrower endpoint or inspect the proxy directly; "
                        "this probe refuses large bodies."
                    ),
                }
            chunks.append(chunk)
        decoded = b"".join(chunks).decode("utf-8", errors="replace")
        try:
            payload = json.loads(decoded) if decoded else None
        except json.JSONDecodeError as exc:
            return {
                "ok": False,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "url": url,
                "content_type": sanitize_text(content_type),
                "error": f"JSONDecodeError: invalid JSON at byte {exc.pos}: {exc.msg}",
                "sample": sanitize_text(decoded),
                "hint": (
                    "Confirm the endpoint returns JSON and that --base-url points "
                    "at the OmniRoute proxy, not a dashboard or reverse-proxy "
                    "error page."
                ),
            }
        if not response.ok:
            return {
                "ok": False,
                "status": status,
                "elapsed_ms": elapsed_ms,
                "url": url,
                "content_type": sanitize_text(content_type),
                "error": f"HTTP {status}: {sanitize_text(response.reason or 'HTTP error')}",
                "sample": sanitize_text(decoded),
                "hint": endpoint_hint(url),
            }
        return {
            "ok": True,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "content_type": sanitize_text(content_type),
            "summary": summarize_payload(payload),
        }
    except requests.RequestException as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return {
            "ok": False,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "url": url,
            "error": f"{type(exc).__name__}: {sanitize_text(exc)}",
            "hint": (
                "Check --base-url, local firewall or tunnel settings, DNS, "
                "TLS certificates, and proxy reachability."
            ),
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
    with requests.Session() as session:
        for target in TARGETS:
            endpoints[target.name] = fetch_json(
                session, join_url(base_url, target.path), api_key, timeout
            )
    return {
        "base_url": base_url,
        "authenticated": bool(api_key),
        "endpoints": endpoints,
    }


def env_registration_commands(base_url: str, api_key_env: str) -> list[str]:
    """Return copy-ready commands for durable user-level OmniRoute env vars."""
    quoted_base = shlex.quote(base_url)
    quoted_api_placeholder = shlex.quote("PASTE_OMNIROUTE_API_KEY_HERE")
    quoted_base_assignment = shlex.quote(f"OMNIROUTE_BASE_URL={base_url}")
    quoted_key_assignment = shlex.quote(f"{api_key_env}=PASTE_OMNIROUTE_API_KEY_HERE")
    return [
        "mkdir -p ~/.config/environment.d",
        "touch ~/.config/environment.d/omniroute.conf",
        (
            "grep -q '^OMNIROUTE_BASE_URL=' ~/.config/environment.d/omniroute.conf || "
            "printf '%s\\n' "
            f"{quoted_base_assignment} "
            ">> ~/.config/environment.d/omniroute.conf"
        ),
        (
            f"grep -q '^{api_key_env}=' ~/.config/environment.d/omniroute.conf || "
            "printf '%s\\n' "
            f"{quoted_key_assignment} "
            ">> ~/.config/environment.d/omniroute.conf"
        ),
        "touch ~/.profile",
        (
            "grep -q '^export OMNIROUTE_BASE_URL=' ~/.profile || "
            "printf '\\nexport OMNIROUTE_BASE_URL=\"${OMNIROUTE_BASE_URL:-%s}\"\\n' "
            f"{quoted_base} >> ~/.profile"
        ),
        (
            f"grep -q '^export {api_key_env}=' ~/.profile || "
            f"printf 'export {api_key_env}=\"${{{api_key_env}:-%s}}\"\\n' "
            f"{quoted_api_placeholder} >> ~/.profile"
        ),
        (
            "printf 'Relaunch terminals, tmux sessions, GUI apps, and Codex/OpenCode "
            "processes before expecting them to inherit the new environment.\\n'"
        ),
    ]


def access_preflight(
    base_url: str,
    api_key_env: str,
    api_key: str | None,
    required_access: str,
    timeout: float,
    include_env_commands: bool,
) -> dict[str, Any]:
    """Check env presence and non-mutating endpoint access for a target level."""
    targets = ACCESS_TARGETS[required_access]
    checks = {}
    with requests.Session() as session:
        for target in targets:
            checks[target.name] = fetch_json(
                session, join_url(base_url, target.path), api_key, timeout
            )
    failed = {
        name: result
        for name, result in checks.items()
        if not isinstance(result, dict) or not result.get("ok")
    }
    env = {
        "base_url_env_set": bool(os.environ.get("OMNIROUTE_BASE_URL")),
        "api_key_env": api_key_env,
        "api_key_env_set": bool(api_key),
        "api_key_value_redacted": "***REDACTED***" if api_key else None,
    }
    notes = [
        "Preflight uses non-mutating GET endpoints only.",
        "A write requirement is treated as admin-compatible read access; actual writes still require explicit user approval.",
        "New terminals, tmux sessions, GUI apps, and already-running CLIs may not inherit env changes until relaunched.",
    ]
    report: dict[str, Any] = {
        "base_url": base_url,
        "required_access": required_access,
        "env": env,
        "access_ok": bool(api_key) and not failed,
        "access_checks": checks,
        "notes": notes,
    }
    if include_env_commands:
        report["registration_commands"] = env_registration_commands(
            base_url, api_key_env
        )
    return report


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
        if not result.get("ok") and result.get("hint"):
            summary = f"{summary}; hint: {result['hint']}"
        lines.append(
            f"| `{sanitize_text(name)}` | {ok} | {status} | {elapsed} ms | "
            f"{sanitize_text(summary)} |"
        )
    lines.extend(
        [
            "",
            "Notes:",
            "- This script only uses read-only endpoints.",
            "- Missing endpoints may indicate server version differences, "
            "disabled features, or auth requirements.",
            "- Capability and rate-limit fields should be treated as partial "
            "unless confirmed by the target server.",
        ]
    )
    return "\n".join(lines)


def render_preflight_markdown(report: dict[str, Any]) -> str:
    """Render preflight output for humans."""
    env = report.get("env", {})
    lines = [
        "# OmniRoute preflight report",
        "",
        f"Base URL: `{report.get('base_url')}`",
        f"Required access: `{report.get('required_access')}`",
        f"API key env var: `{env.get('api_key_env')}`",
        f"API key present: `{'yes' if env.get('api_key_env_set') else 'no'}`",
        f"Access compatible: `{'yes' if report.get('access_ok') else 'no'}`",
        "",
        "| Check | OK | Status | Detail |",
        "|---|---:|---:|---|",
    ]
    checks = report.get("access_checks", {})
    if isinstance(checks, dict):
        for name, result in checks.items():
            if not isinstance(result, dict):
                continue
            detail = result.get("summary") if result.get("ok") else result.get("error")
            if not result.get("ok") and result.get("hint"):
                detail = f"{detail}; hint: {result['hint']}"
            status = result.get("status") if result.get("status") is not None else "n/a"
            lines.append(
                f"| `{sanitize_text(name)}` | {'yes' if result.get('ok') else 'no'} | "
                f"{status} | {sanitize_text(detail)} |"
            )
    commands = report.get("registration_commands")
    if isinstance(commands, list) and commands:
        lines.extend(["", "## Persistent user env registration", ""])
        lines.append("Run these in a terminal, replacing `PASTE_OMNIROUTE_API_KEY_HERE` with the real key:")
        lines.append("")
        lines.append("```bash")
        lines.extend(str(command) for command in commands)
        lines.append("```")
    notes = report.get("notes")
    if isinstance(notes, list) and notes:
        lines.extend(["", "Notes:"])
        lines.extend(f"- {sanitize_text(note)}" for note in notes)
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
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="Check required OmniRoute env vars and non-mutating access compatibility",
    )
    parser.add_argument(
        "--required-access",
        choices=["runtime", "read", "write", "admin"],
        default="runtime",
        help="Access level to check when --preflight is used",
    )
    parser.add_argument(
        "--print-env-commands",
        action="store_true",
        help="Include durable user-level env registration commands in preflight output",
    )
    parser.add_argument(
        "--fail-on-incompatible",
        action="store_true",
        help="Return exit code 1 when --preflight access is not compatible",
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
        if args.preflight:
            if not api_key_env:
                raise ValueError("--preflight requires a non-empty --api-key-env")
            report = access_preflight(
                base_url,
                api_key_env,
                api_key,
                args.required_access,
                args.timeout,
                args.print_env_commands,
            )
        else:
            report = run_probe(base_url, api_key, args.timeout)
    except ValueError as exc:
        print(
            "omniroute_discover.py: invalid input: "
            f"{sanitize_text(exc)}. "
            "Use --base-url with an http(s) URL that has no embedded credentials, "
            "set --api-key-env to the name of an environment variable, and keep "
            "--timeout within 0-60 seconds.",
            file=sys.stderr,
        )
        return 2

    if args.markdown:
        if args.preflight:
            print(render_preflight_markdown(report))
        else:
            print(render_markdown(report))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    if args.preflight and args.fail_on_incompatible and not report.get("access_ok"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

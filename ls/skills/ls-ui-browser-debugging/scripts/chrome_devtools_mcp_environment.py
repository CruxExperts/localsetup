#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any


SKILL_NAME = "ls-ui-browser-debugging"
MCP_NAME = "chrome-devtools"
MCP_PACKAGE = "chrome-devtools-mcp@latest"
PINNED_SNAPSHOT = {
    "package": "chrome-devtools-mcp",
    "version": "1.8.0",
    "access_date": "2026-09-04",
    "source": "https://registry.npmjs.org/chrome-devtools-mcp/latest",
}
DEFAULT_PROFILE_RELATIVE = ".localsetup-maint/ui-browser-profiles/chrome-devtools"
PRIVACY_ARGS = [
    "-y",
    MCP_PACKAGE,
    "--no-usage-statistics",
    "--no-performance-crux",
    "--redactNetworkHeaders",
]
ISOLATED_ARGS = [*PRIVACY_ARGS, "--isolated=true"]
SUPPORTED_AGENTS = {"codex", "claude-code", "cursor", "kilo", "opencode", "openclaw"}


def repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def command_fact(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"name": name, "available": path is not None, "path": path}


def chrome_candidates() -> list[str]:
    system = platform.system().lower()
    if system == "darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]
    if system == "windows":
        roots = [
            os.environ.get("PROGRAMFILES"),
            os.environ.get("PROGRAMFILES(X86)"),
            os.environ.get("LOCALAPPDATA"),
        ]
        names = [
            "Google/Chrome/Application/chrome.exe",
            "Google/Chrome SxS/Application/chrome.exe",
            "Chromium/Application/chrome.exe",
        ]
        return [str(Path(root) / name) for root in roots if root for name in names]
    return [
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "chrome",
    ]


def chrome_fact() -> dict[str, Any]:
    found: list[str] = []
    checked: list[str] = []
    for candidate in chrome_candidates():
        path = shutil.which(candidate) if "/" not in candidate else (candidate if Path(candidate).exists() else None)
        checked.append(candidate)
        if path:
            found.append(path)
    return {"available": bool(found), "paths": found, "checked": checked}


def resolve_state_root(value: str | Path | None) -> Path:
    root = repo_root() if value is None else Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("state root must be an absolute path")
    return root.resolve()


def persistent_profile_dir(state_root: str | Path | None) -> Path:
    return resolve_state_root(state_root) / DEFAULT_PROFILE_RELATIVE


def standard_config(mode: str = "isolated", state_root: str | Path | None = None) -> dict[str, Any]:
    if mode not in {"isolated", "persistent"}:
        raise ValueError("mode must be isolated or persistent")
    if mode == "persistent" and state_root is None:
        raise ValueError("persistent mode requires an explicit absolute state root")
    root = resolve_state_root(state_root) if state_root is not None or mode == "persistent" else None
    profile = persistent_profile_dir(root) if root is not None else None
    args = ISOLATED_ARGS if mode == "isolated" else [*PRIVACY_ARGS, f"--userDataDir={profile}"]
    return {
        "name": MCP_NAME,
        "mode": mode,
        "transport": "stdio",
        "command": "npx",
        "args": args,
        "state_root": str(root) if root is not None else None,
        "recommended_profile_dir": None if mode == "isolated" else str(profile),
        "persistent_profile_dir": str(profile) if profile is not None else None,
        "pinned_reproducibility_snapshot": PINNED_SNAPSHOT,
    }


def inspect(require: bool, state_root: str | Path | None = None) -> tuple[dict[str, Any], int]:
    root = resolve_state_root(state_root)
    profile = persistent_profile_dir(root)
    node = command_fact("node")
    npx = command_fact("npx")
    chrome = chrome_fact()
    warnings: list[str] = []
    errors: list[str] = []

    if not node["available"]:
        warnings.append("node was not found on PATH; npx-based MCP startup will not work.")
    if not npx["available"]:
        warnings.append("npx was not found on PATH; the recommended stdio command cannot run.")
    if not chrome["available"]:
        warnings.append("Chrome/Chromium was not found by common executable probes; configure a channel or executable path if needed.")

    if require:
        if not node["available"]:
            errors.append("node is required when --require is used.")
        if not npx["available"]:
            errors.append("npx is required when --require is used.")
        if not chrome["available"]:
            errors.append("Chrome/Chromium is required when --require is used.")

    payload = {
        "schema_version": 1,
        "skill": SKILL_NAME,
        "status": "ok" if not errors else "missing_requirements",
        "host": {
            "platform": platform.platform(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "commands": {"node": node, "npx": npx},
        "chrome": chrome,
        "profile": {
            "path": str(profile),
            "exists": profile.exists(),
            "state_root": str(root),
            "recommended_relative_path": DEFAULT_PROFILE_RELATIVE,
        },
        "recommended_mcp_server": standard_config(state_root=root),
        "warnings": warnings,
        "errors": errors,
    }
    return payload, 1 if errors else 0


def example(agent: str) -> dict[str, Any]:
    if agent not in SUPPORTED_AGENTS:
        return {
            "schema_version": 1,
            "agent": agent,
            "status": "unsupported_agent",
            "supported_agents": sorted(SUPPORTED_AGENTS),
        }

    config = standard_config()
    if agent == "codex":
        return {
            "schema_version": 1,
            "agent": agent,
            "status": "source_backed",
            "source": "https://developers.openai.com/codex/mcp",
            "example": {
                "format": "toml",
                "path": "~/.codex/config.toml or trusted project .codex/config.toml",
                "snippet": (
                    "[mcp_servers.chrome-devtools]\n"
                    'command = "npx"\n'
                    f"args = {json.dumps(config['args'])}\n"
                ),
            },
        }
    if agent == "cursor":
        return {
            "schema_version": 1,
            "agent": agent,
            "status": "source_backed",
            "source": "https://cursor.com/docs/mcp",
            "example": {
                "format": "json",
                "path": ".cursor/mcp.json or ~/.cursor/mcp.json",
                "snippet": json.dumps({"mcpServers": {MCP_NAME: {"command": config["command"], "args": config["args"]}}}, indent=2),
            },
        }
    if agent == "kilo":
        return {
            "schema_version": 1,
            "agent": agent,
            "status": "source_backed",
            "source": "https://kilo.ai/docs/automate/mcp/using-in-kilo-code",
            "example": {
                "format": "json",
                "path": "~/.config/kilo/kilo.json[c], ./kilo.json[c], or ./.kilo/kilo.json[c]",
                "snippet": json.dumps(
                    {
                        "mcp": {
                            MCP_NAME: {
                                "type": "local",
                                "command": [config["command"], *config["args"]],
                            }
                        }
                    },
                    indent=2,
                ),
            },
        }
    if agent == "opencode":
        return {
            "schema_version": 1,
            "agent": agent,
            "status": "source_backed",
            "source": "https://opencode.ai/docs/mcp-servers/",
            "example": {
                "format": "json",
                "path": "~/.config/opencode/opencode.json[c] or project-root opencode.json[c]",
                "snippet": json.dumps(
                    {
                        "$schema": "https://opencode.ai/config.json",
                        "mcp": {
                            MCP_NAME: {
                                "type": "local",
                                "command": [config["command"], *config["args"]],
                            }
                        },
                    },
                    indent=2,
                ),
            },
        }

    return {
        "schema_version": 1,
        "agent": agent,
        "status": "documentation_required",
        "message": "Use this platform's current native MCP docs or discovery command before writing config syntax.",
        "standard_config": config,
    }


def emit(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"{payload.get('skill') or payload.get('agent') or payload.get('status')}: {payload.get('status', 'ok')}")
    warnings = payload.get("warnings") or []
    errors = payload.get("errors") or []
    for warning in warnings:
        print(f"warning: {warning}")
    for error in errors:
        print(f"error: {error}")
    if "mcp_server" in payload:
        server = payload["mcp_server"]
        print(f"command: {server['command']} {' '.join(server['args'])}")
    if "example" in payload:
        print(payload["example"]["snippet"])
    elif "standard_config" in payload:
        server = payload["standard_config"]
        print(f"standard-config: {server['command']} {' '.join(server['args'])}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Chrome DevTools MCP host readiness and emit read-only config examples.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="Report host facts and warning-only readiness checks.")
    inspect_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    inspect_parser.add_argument("--require", action="store_true", help="Exit non-zero when node, npx, or Chrome are missing.")
    inspect_parser.add_argument("--state-root", help="Absolute project/state root used to resolve the dedicated profile path.")

    standard_parser = subparsers.add_parser("standard-config", help="Emit a client-neutral MCP server definition.")
    standard_parser.add_argument(
        "--mode",
        choices=["isolated", "persistent"],
        default="isolated",
        help="Browser profile mode. Defaults to isolated ephemeral sessions.",
    )
    standard_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    standard_parser.add_argument(
        "--state-root",
        help="Absolute project/state root; required for persistent mode so --userDataDir never depends on process cwd.",
    )

    example_parser = subparsers.add_parser("example", help="Emit a source-backed agent config example when available.")
    example_parser.add_argument("--agent", required=True, help="Agent platform id.")
    example_parser.add_argument("--json", action="store_true", help="Print JSON output.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "inspect":
        payload, code = inspect(require=args.require, state_root=args.state_root)
        emit(payload, args.json)
        return code
    if args.command == "standard-config":
        try:
            config = standard_config(args.mode, args.state_root)
        except ValueError as error:
            build_parser().error(str(error))
        emit({"schema_version": 1, "status": "ok", "mcp_server": config}, args.json)
        return 0
    if args.command == "example":
        emit(example(args.agent), args.json)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())

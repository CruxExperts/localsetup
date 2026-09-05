#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


REQUIRED_FILES = [
    "SKILL.md",
    "references/source-ledger.md",
    "references/mcp-bootstrap-and-repair.md",
    "references/browser-session-management.md",
    "references/ui-feasibility-review.md",
    "references/subagent-browser-workflows.md",
    "references/browser-mcp-landscape.md",
    "scripts/browser_session_guard.py",
    "scripts/chrome_devtools_mcp_environment.py",
    "scripts/verify_ui_browser_debugging_sources.py",
]
REQUIRED_PHRASES = {
    "SKILL.md": [
        "name: ls-ui-browser-debugging",
        "Chrome DevTools MCP",
        "--no-usage-statistics",
        "--no-performance-crux",
        "--redactNetworkHeaders",
        "--isolated=true",
        "browser_session_guard.py",
    ],
    "references/browser-session-management.md": [
        '"schema_version": 3',
        '"status": "active"',
        '"mcp_session_id"',
        '"state_root"',
        '"owner": "<agent/platform>"',
        '"may_close": true',
        "cleanup_actions",
        "list_pages",
        "new_page",
        "select_page",
        "close_page",
        "stale session recovery",
        "page.close()",
        "context.close()",
        "browser.close()",
        "Concurrent browser control requires",
    ],
    "references/subagent-browser-workflows.md": [
        "--pageIdRouting",
        "--mcp-session-id",
        "--page-owner",
        "shared controller-owned routed-server record",
        "must not use live browser MCP tools",
        "close_page",
    ],
    "references/browser-mcp-landscape.md": [
        "--isolated=true",
        "--userDataDir",
        "--pageIdRouting",
        "Chrome 136",
        "list_pages",
        "close_page",
        "context.close()",
    ],
    "references/source-ledger.md": [
        "Accessed: 2026-09-04.",
        "https://developer.chrome.com/blog/remote-debugging-port",
        "https://developer.chrome.com/docs/devtools/agents",
        "https://github.com/ChromeDevTools/chrome-devtools-mcp",
        "https://playwright.dev/docs/getting-started-mcp",
        "https://playwright.dev/docs/pages",
        "https://modelcontextprotocol.io/docs/getting-started/intro",
        "https://cursor.com/docs/mcp",
        "https://kilo.ai/docs/automate/mcp/using-in-kilo-code",
        "https://opencode.ai/docs/mcp-servers/",
        "https://docs.openclaw.ai/cli/mcp",
    ],
}
SOURCE_URLS = [
    "https://developer.chrome.com/docs/devtools/agents",
    "https://github.com/ChromeDevTools/chrome-devtools-mcp",
    "https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/chrome-devtools-mcp-v1.8.0/src/config/mcp-options.ts",
    "https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/CHANGELOG.md",
    "https://developer.chrome.com/blog/remote-debugging-port",
    "https://playwright.dev/docs/getting-started-mcp",
    "https://playwright.dev/docs/getting-started-cli",
    "https://playwright.dev/docs/browsers",
    "https://playwright.dev/docs/pages",
    "https://modelcontextprotocol.io/docs/getting-started/intro",
    "https://developers.openai.com/codex/mcp",
    "https://code.claude.com/docs/en/mcp",
    "https://cursor.com/docs/mcp",
    "https://cursor.com/docs/cli/mcp",
    "https://kilo.ai/docs/automate/mcp/using-in-kilo-code",
    "https://opencode.ai/docs/mcp-servers/",
    "https://opencode.ai/docs/config/",
    "https://docs.openclaw.ai/cli/mcp",
]
NPM_VERSION_SNAPSHOT = {
    "chrome-devtools-mcp": "1.8.0",
    "@playwright/mcp": "0.0.80",
    "@playwright/cli": "0.1.19",
    "playwright": "1.62.1",
}


def skill_root() -> Path:
    return Path(__file__).resolve().parents[1]


def check_static(root: Path) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for rel in REQUIRED_FILES:
        path = root / rel
        if not path.is_file():
            issues.append({"path": rel, "severity": "error", "message": "required file is missing"})
    for rel, phrases in REQUIRED_PHRASES.items():
        path = root / rel
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase not in text:
                issues.append({"path": rel, "severity": "error", "message": f"required phrase missing: {phrase}"})
    return issues


def check_url(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "localsetup-ui-browser-debugging-verifier/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return {"url": url, "ok": 200 <= response.status < 400, "status": response.status}
    except Exception as error:  # pragma: no cover - network-dependent detail
        return {"url": url, "ok": False, "error": str(error)}


def npm_metadata_url(package: str) -> str:
    return f"https://registry.npmjs.org/{package.replace('/', '%2f')}/latest"


def check_npm_version(package: str, expected: str, timeout: float) -> dict[str, Any]:
    url = npm_metadata_url(package)
    request = urllib.request.Request(url, headers={"User-Agent": "localsetup-ui-browser-debugging-verifier/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as error:  # pragma: no cover - network-dependent detail
        return {"package": package, "url": url, "expected": expected, "ok": False, "error": str(error)}
    actual = payload.get("version")
    return {
        "package": package,
        "url": url,
        "expected": expected,
        "actual": actual,
        "ok": actual == expected,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify ls-ui-browser-debugging source structure, URL reachability, and structured npm version snapshots.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Check URL reachability and exact npm registry versions; URL success does not semantically verify a cited claim.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-source network timeout in seconds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = skill_root()
    issues = check_static(root)
    source_reachability: list[dict[str, Any]] = []
    npm_versions: list[dict[str, Any]] = []
    if args.refresh:
        source_reachability = [check_url(url, args.timeout) for url in SOURCE_URLS]
        for result in source_reachability:
            if not result.get("ok"):
                issues.append({"path": result["url"], "severity": "warning", "message": "source URL was not reachable"})
        npm_versions = [check_npm_version(package, version, args.timeout) for package, version in NPM_VERSION_SNAPSHOT.items()]
        for result in npm_versions:
            if not result.get("ok"):
                issues.append(
                    {
                        "path": result["package"],
                        "severity": "error",
                        "message": f"npm version snapshot drift: expected {result.get('expected')}, got {result.get('actual') or result.get('error')}",
                    }
                )

    has_errors = any(issue["severity"] == "error" for issue in issues)
    payload = {
        "schema_version": 1,
        "skill": "ls-ui-browser-debugging",
        "status": "failed" if has_errors else "ok",
        "root": str(root),
        "issues": issues,
        "source_reachability": source_reachability,
        "source_reachability_limitation": "HTTP success confirms reachability only; it does not verify that a page still supports a cited claim.",
        "npm_versions": npm_versions,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['skill']}: {payload['status']}")
        for issue in issues:
            print(f"{issue['severity']}: {issue['path']}: {issue['message']}")
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())

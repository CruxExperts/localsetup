---
name: ls-ui-browser-debugging
description: "UI review and browser-driven debugging workflow for Chrome DevTools MCP, Playwright MCP/CLI, browser ownership, evidence capture, minimal fixes, and durable UI regression tests."
metadata:
  version: "1.0"
compatibility:
  notes:
    - "Includes read-only helpers for Chrome DevTools MCP environment inspection and source freshness checks."
---

# UI Browser Debugging

Use this skill for UI review, browser-driven debugging, visual/a11y feasibility
checks, console or network triage, Chrome DevTools MCP setup repair, and turning
confirmed UI issues into durable Playwright or project-native regression tests.

## First Inspect The Project

Before opening a browser:

- Identify the app root, package manager, dev-server command, target route, and
  existing UI/e2e test stack.
- Detect browser MCP tools already available in the active agent. If Chrome
  DevTools MCP tools are usable, use them and do not offer setup.
- If tools are missing, inspect the active agent's MCP profiles with that
  agent's native discovery command or current docs.
- If a Chrome DevTools MCP profile exists, prefer use or repair guidance before
  proposing bootstrap.
- Bootstrap only when no usable profile exists, translating the standard MCP
  server definition through current source-backed agent docs.

## Decision Flow

- **MCP missing or misconfigured:** use
  [MCP bootstrap and repair](./references/mcp-bootstrap-and-repair.md).
- **Browser ownership or cleanup:** use
  [browser session management](./references/browser-session-management.md).
- **UI critique and debugging:** use
  [UI feasibility review](./references/ui-feasibility-review.md).
- **Multi-agent work:** use
  [subagent browser workflows](./references/subagent-browser-workflows.md).
- **Tool choice or current facts:** use
  [browser MCP landscape](./references/browser-mcp-landscape.md).

## Chrome DevTools MCP Defaults

Upstream Chrome DevTools MCP enables usage statistics and CrUX field data for
performance work by default. Network-header redaction and isolated profiles are
disabled upstream by default.

For local agent work, prefer privacy-oriented defaults:

```bash
npx -y chrome-devtools-mcp@latest \
  --user-data-dir=.localsetup-maint/ui-browser-profiles/chrome-devtools \
  --no-usage-statistics \
  --no-performance-crux \
  --redactNetworkHeaders
```

Use a dedicated profile for agent-owned sessions. Do not attach to a user's
everyday Chrome profile unless the user explicitly authorizes that browser
state.

## Helper Commands

```bash
python3 scripts/chrome_devtools_mcp_environment.py inspect --json
python3 scripts/chrome_devtools_mcp_environment.py inspect --json --require
python3 scripts/chrome_devtools_mcp_environment.py standard-config --json
python3 scripts/chrome_devtools_mcp_environment.py example --agent codex --json
python3 scripts/verify_ui_browser_debugging_sources.py
python3 scripts/verify_ui_browser_debugging_sources.py --refresh --json
```

The helpers are read-only. They do not edit agent config, delete profiles, kill
browsers, install packages, or change existing MCP profiles.

## Evidence Rules

- Prefer `take_snapshot` for interaction targets and accessibility structure.
- Use screenshots for visual layout evidence.
- Use console, network, Lighthouse, and performance traces only when relevant
  and available.
- Degrade gracefully when the MCP profile is `--slim` or omits network,
  performance, Lighthouse, or screenshot capabilities.
- Record compact evidence: route, viewport, page id, observed issue, tool used,
  and artifact path when one exists.
- Convert confirmed user-facing issues into a focused regression test whenever
  the project has a suitable test stack.

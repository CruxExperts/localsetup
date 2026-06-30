# Browser MCP Landscape

Accessed: 2026-06-29.

## Tool Roles

Chrome DevTools MCP is the primary live Chrome inspection path for UI debugging
when the task needs DevTools-level page state, console, network, Lighthouse, or
performance trace evidence.

Playwright MCP is useful for structured browser interaction and page state
inspection through accessibility snapshots. Playwright CLI/Test is the durable
automation path for regression tests after a UI issue is confirmed.

## Dated Version Snapshot

These values are volatile and must be rechecked before version-sensitive work:

- `chrome-devtools-mcp`: 1.4.0 on npm, checked 2026-06-29.
- `@playwright/mcp`: 0.0.77 on npm, checked 2026-06-29.
- `@playwright/cli`: 0.1.14 on npm, checked 2026-06-29.
- `playwright`: 1.61.1 on npm, checked 2026-06-29.

The recommended setup examples use `chrome-devtools-mcp@latest` so normal agent
config picks up current fixes. Pin a version only for a dated reproduction or
controlled rollback.

## Capability Notes

- Prefer snapshots before screenshots for interaction and accessibility
  structure.
- Use screenshots for visual layout evidence.
- Use network, Lighthouse, and performance categories only when relevant and
  available.
- If a server runs with a slim or restricted tool set, record the missing
  category and use the nearest available evidence path.
- Do not treat MCP output as a security boundary. Keep secrets out of traces,
  logs, headers, screenshots, and saved artifacts.

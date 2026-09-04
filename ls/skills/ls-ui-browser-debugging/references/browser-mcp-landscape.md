# Browser MCP Landscape

Accessed: 2026-09-04.

## Tool Roles

Chrome DevTools MCP is the primary live Chrome inspection path for UI debugging
when the task needs DevTools-level page state, console, network, Lighthouse, or
performance trace evidence.

Playwright MCP is useful for structured browser interaction and page state
inspection through accessibility snapshots. Playwright CLI/Test is the durable
automation path for regression tests after a UI issue is confirmed.

## Session Controls

Use Chrome DevTools MCP page tools deliberately:

- `list_pages` before opening a page.
- `new_page` only when reuse of the owned active page is not appropriate.
- `select_page` for a recorded owned page or an explicitly authorized
  pre-existing page.
- `close_page` only for recorded agent-owned pages.

Use `--isolated=true` for default ephemeral sessions. Use `--userDataDir` with
the dedicated absolute `.localsetup-maint/ui-browser-profiles/chrome-devtools`
profile derived from an explicit project/state root only when login or state
reuse is required. Chrome 136 restricts remote
debugging against the default Chrome profile, so agent automation must not use a
user's everyday profile unless the user explicitly authorizes a supported
non-default profile flow.

Chrome DevTools MCP 1.8.0 enables `--pageIdRouting` by default and requires page
ids for page-scoped tools. For multi-agent control, give each actor an explicit
page id on one routed server or a separately owned isolated MCP server instance
with a unique session id. Otherwise keep live browser control serial.

## Dated Version Snapshot

These values are volatile and must be rechecked before version-sensitive work:

- `chrome-devtools-mcp`: 1.8.0 on npm, checked 2026-09-04.
- `@playwright/mcp`: 0.0.80 on npm, checked 2026-09-04.
- `@playwright/cli`: 0.1.19 on npm, checked 2026-09-04.
- `playwright`: 1.62.1 on npm, checked 2026-09-04.

The Playwright MCP and CLI packages currently depend on a Playwright 1.63 alpha;
do not infer that their bundled engine matches standalone `playwright@latest`.

The recommended setup examples use `chrome-devtools-mcp@latest` so normal agent
config picks up current fixes. Pin a version only for a dated reproduction or
controlled rollback.

## Capability Notes

- Prefer snapshots before screenshots for interaction and accessibility
  structure.
- Reuse the owned active page for the same app or route family unless the task
  needs independent state, destructive navigation, or parallel comparison.
- Use screenshots for visual layout evidence.
- Use network, Lighthouse, and performance categories only when relevant and
  available.
- If a server runs with a slim or restricted tool set, record the missing
  category and use the nearest available evidence path.
- Do not treat MCP output as a security boundary. Keep secrets out of traces,
  logs, headers, screenshots, and saved artifacts.
- For Playwright-driven reproduction or tests, prefer one browser with isolated
  contexts and explicit cleanup through `page.close()`, `context.close()`, and
  `browser.close()`.

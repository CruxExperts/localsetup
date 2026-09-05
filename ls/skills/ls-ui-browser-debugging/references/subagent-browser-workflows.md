# Subagent Browser Workflows

The controller owns browser sessions. Use subagents for bounded work that does
not require concurrent control of the same page.

## Good Delegations

- `explorer`: map UI routes, component owners, test commands, and likely files.
- `researcher`: verify current MCP docs, browser tool behavior, or library
  testing docs from primary sources.
- `worker`: make one bounded code or test change after the controller has
  confirmed the issue and file scope.
- `tester`: run focused tests, lint, Playwright tests, or screenshot-diff tools.
- `reviewer`: inspect the diff, evidence, safety, and regression coverage.

## Browser Boundaries

- Do not ask subagents to drive the same browser page concurrently.
- A subagent may drive a browser only when the controller assigns one of these
  ownership models before the subagent starts:
  - Default-on `--pageIdRouting` with an explicit page id assigned to that
    subagent on one shared, controller-owned MCP server record; do not disable
    routing with `--no-page-id-routing`.
  - A separate isolated Chrome DevTools MCP server instance with a unique,
    controller-assigned MCP session id owned by that subagent.
- For a shared routed server, the controller starts one record for the server
  and records every assigned page with `--page-owner <agent>` before that actor
  uses it. Subagents do not create separate records that claim the shared MCP
  server.
- For a separate isolated server, start `browser_session_guard.py` with its
  unique MCP session id as both `--session-id` and `--mcp-session-id`. In both
  models, record the page id, page owner, purpose, and the same absolute state
  root before use.
- If neither page-id routing nor an isolated MCP instance is assigned, the subagent
  must not use live browser MCP tools. It may review saved screenshots,
  snapshots, console excerpts, traces, or run non-browser tests.
- Subagents may review screenshots, snapshots, console excerpts, and traces
  saved by the controller.
- The controller verifies subagent findings before marking an issue fixed.

## Closeout

The controller owns final browser closeout. At task end, audit every applicable
record: the shared controller-owned routed-server record and each separately
isolated subagent-owned record. Close only recorded owned pages with
`close_page`, mark them closed, and leave user or pre-existing pages alone
unless the user explicitly authorized closing them.

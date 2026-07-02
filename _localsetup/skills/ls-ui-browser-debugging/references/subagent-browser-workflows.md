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
  - `--experimentalPageIdRouting` with an explicit page id assigned to that
    subagent.
  - A separate isolated profile or isolated Chrome DevTools MCP session owned
    by that subagent.
- Record the assigned page id, isolated profile, owner, and purpose with
  `browser_session_guard.py` before the subagent uses the page.
- If neither page-id routing nor an isolated profile is assigned, the subagent
  must not use live browser MCP tools. It may review saved screenshots,
  snapshots, console excerpts, traces, or run non-browser tests.
- Subagents may review screenshots, snapshots, console excerpts, and traces
  saved by the controller.
- The controller verifies subagent findings before marking an issue fixed.

## Closeout

The controller owns final browser closeout. At task end, each subagent-owned
record must be audited. Close only recorded owned pages with `close_page`, mark
them closed, and leave user or pre-existing pages alone unless the user
explicitly authorized closing them.

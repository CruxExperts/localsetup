# Browser Session Management

Browser control defaults to one serial controller-owned session. Subagents can
inspect code, run tests, or review saved artifacts, but they should not drive
the same browser concurrently.

## Ownership Record

Record browser ownership in the current run ledger when one exists. Otherwise
write a private record under:

```text
.localsetup-maint/ui-browser-sessions/<session-id>.json
```

Schema:

```json
{
  "schema_version": 1,
  "session_id": "<timestamp-or-run-id>",
  "controller": "<agent/platform>",
  "mcp_server": "chrome-devtools",
  "profile_dir": "<agent-owned-profile>",
  "routing": "selected-page|page-id-routing|isolated-profile",
  "active_page_id": 0,
  "pages": [
    {
      "pageId": 0,
      "url": "http://localhost:3000",
      "opened_by": "controller",
      "purpose": "ui-debug",
      "may_close": true
    }
  ]
}
```

## Page Rules

- Start with page discovery.
- Reuse one agent-owned page for the same app and route family when practical.
- Open a new page when a workflow needs independent state, a different app, or
  a destructive navigation.
- Close only pages marked `may_close: true`.
- Do not close pages that predate the session or are not recorded as
  agent-owned.

## Concurrency

Concurrent browser control requires one of these models:

- Chrome DevTools MCP page-id routing with each actor assigned a specific page.
- Separate isolated browser profiles per actor.

If neither model is configured, keep browser actions serial and controller-run.

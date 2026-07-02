# Browser Session Management

Browser control defaults to one serial controller-owned session with isolated,
ephemeral browser state. Use persistent browser state only when login or state
reuse is part of the task, and then use a dedicated agent-owned profile.

## Lifecycle Contract

Follow this order for Chrome DevTools MCP sessions:

1. Run `list_pages` before opening a new page.
2. Reuse the owned active page for the same app or route family when practical.
3. Use `new_page` only for independent state, destructive navigation, a
   different app, or parallel comparison.
4. Record every agent-created page with `browser_session_guard.py record-page`
   before use.
5. Use `select_page` only for a recorded owned page, unless the user explicitly
   authorizes taking over a pre-existing page.
6. At task end, close owned pages with `close_page`, then mark them closed in
   the session record.
7. Never close user pages, pre-existing pages, or pages not recorded as
   agent-owned unless the user explicitly authorizes that action.

The helper manages records and cleanup guidance only. It does not call MCP
tools, close browser pages, delete profiles, or kill browser processes.

## Ownership Record

Create or update browser ownership in the current run ledger when one exists,
and keep the private machine-readable record under:

```text
.localsetup-maint/ui-browser-sessions/<session-id>.json
```

Use:

```bash
python3 scripts/browser_session_guard.py start --tool chrome-devtools --mode isolated --owner <agent> --purpose <text> --json
python3 scripts/browser_session_guard.py record-page --session-id <id> --page-id <id> --url <url> --purpose <text> --json
python3 scripts/browser_session_guard.py select-page --session-id <id> --page-id <id> --json
python3 scripts/browser_session_guard.py mark-closed --session-id <id> --page-id <id> --json
python3 scripts/browser_session_guard.py finish --session-id <id> --json
python3 scripts/browser_session_guard.py audit --session-id <id> --json
```

Schema version 2:

```json
{
  "schema_version": 2,
  "skill": "ls-ui-browser-debugging",
  "session_id": "<safe-session-id>",
  "status": "active",
  "mode": "isolated",
  "tool": "chrome-devtools",
  "owner": "<agent/platform>",
  "purpose": "ui-debug",
  "profile_dir": null,
  "active_page_id": "<page-id-or-null>",
  "pages": [
    {
      "page_id": "<page-id>",
      "url": "http://localhost:3000",
      "purpose": "ui-debug",
      "owned": true,
      "may_close": true,
      "status": "open"
    }
  ],
  "cleanup_actions": [
    {
      "action": "close_page",
      "tool": "chrome-devtools",
      "page_id": "<page-id>",
      "url": "http://localhost:3000",
      "instruction": "Use Chrome DevTools MCP close_page for this owned page, then mark it closed."
    }
  ]
}
```

Version 1 records that used `controller`, `mcp_server`, `routing`, `pageId`, and
`may_close` remain readable. The guard upgrades them when it writes the record.

## Page Rules

- Treat `list_pages` output as discovery, not ownership. A page is owned only
  after the agent created it and recorded it.
- Prefer page reuse for route changes in the same app unless the workflow needs
  independent browser state.
- `finish` exits non-zero when owned pages remain open. Follow each
  `cleanup_actions` entry, then run `mark-closed` and `finish` again.
- If an MCP session or browser process is stale, run `audit` for the session id
  before creating a replacement. Clean up recorded owned pages first when the
  MCP tool can still reach them.
- If stale session recovery cannot confirm a page is agent-owned, leave it open
  and report the manual cleanup need instead of closing it.

## Playwright Cleanup

When using Playwright directly for reproduction or regression tests, keep the
same ownership model. Prefer one browser with isolated contexts, and put
cleanup in `finally` or fixture teardown with explicit `page.close()`,
`context.close()`, and `browser.close()` paths. Saved artifacts may be reviewed
by subagents without giving them live browser control.

## Concurrency

Concurrent browser control requires one of these models:

- Chrome DevTools MCP page-id routing with each actor assigned a specific page.
- Separate isolated browser profiles per actor.

If neither model is configured, keep browser actions serial and controller-run.

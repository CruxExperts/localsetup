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
- If a subagent needs browser control, assign an isolated profile or a specific
  page-id routing model and record it in the ownership record.
- Subagents may review screenshots, snapshots, console excerpts, and traces
  saved by the controller.
- The controller verifies subagent findings before marking an issue fixed.

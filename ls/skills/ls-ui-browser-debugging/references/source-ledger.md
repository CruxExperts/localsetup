# Source Ledger

Accessed: 2026-09-04.

This ledger records source-backed claims used by `ls-ui-browser-debugging`.
Re-check volatile package versions, support status, and agent-specific config
syntax before editing version-sensitive public claims. The bundled verifier's
non-npm HTTP checks establish URL reachability only, not semantic freshness.

## Primary Sources

- Chrome DevTools for agents:
  https://developer.chrome.com/docs/devtools/agents
- Chrome DevTools MCP repository:
  https://github.com/ChromeDevTools/chrome-devtools-mcp
- Chrome DevTools MCP 1.8.0 configuration source:
  https://raw.githubusercontent.com/ChromeDevTools/chrome-devtools-mcp/chrome-devtools-mcp-v1.8.0/src/config/mcp-options.ts
- Chrome DevTools MCP changelog:
  https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/CHANGELOG.md
- Chrome DevTools MCP package metadata:
  https://www.npmjs.com/package/chrome-devtools-mcp
- Chrome remote debugging profile restriction:
  https://developer.chrome.com/blog/remote-debugging-port
- Playwright MCP:
  https://playwright.dev/docs/getting-started-mcp
- Playwright CLI:
  https://playwright.dev/docs/getting-started-cli
- Playwright browsers:
  https://playwright.dev/docs/browsers
- Playwright pages:
  https://playwright.dev/docs/pages
- Model Context Protocol introduction:
  https://modelcontextprotocol.io/docs/getting-started/intro
- Codex MCP documentation:
  https://developers.openai.com/codex/mcp
- Claude Code MCP documentation:
  https://code.claude.com/docs/en/mcp
- Cursor MCP documentation:
  https://cursor.com/docs/mcp
- Cursor CLI MCP documentation:
  https://cursor.com/docs/cli/mcp
- Kilo MCP documentation:
  https://kilo.ai/docs/automate/mcp/using-in-kilo-code
- OpenCode MCP documentation:
  https://opencode.ai/docs/mcp-servers/
- OpenCode config documentation:
  https://opencode.ai/docs/config/
- OpenClaw MCP documentation:
  https://docs.openclaw.ai/cli/mcp

## Verified Claims

- Chrome DevTools MCP is an MCP server for controlling and inspecting Chrome
  through DevTools. It is distributed for agent configuration through `npx` with
  `chrome-devtools-mcp@latest`.
- Chrome DevTools MCP upstream documents opt-out flags for usage statistics and
  CrUX performance data. It also documents redaction of selected sensitive
  network headers and browser profile isolation controls; redaction is not an
  absolute secrecy guarantee.
- Chrome DevTools MCP upstream defaults are not privacy-maximal for local agent
  work: usage statistics and CrUX field-data lookup are enabled by default,
  while network-header redaction and isolated profiles are disabled by default.
- Chrome DevTools MCP exposes page lifecycle tools including `list_pages`,
  `new_page`, `select_page`, and `close_page`, so agent workflows can list
  before opening, reuse or select explicit pages, and close only pages they own.
- Chrome DevTools MCP documents `--isolated` and `--userDataDir` controls for
  isolated sessions and explicit persistent profile directories. In 1.8.0,
  `--pageIdRouting` graduated from its experimental name, defaults to true, and
  requires page ids for page-scoped tools.
- Chrome 136 restricts remote debugging switches against the default Chrome
  data directory. Agent automation should use isolated sessions or a non-default
  dedicated profile rather than a user's everyday Chrome profile.
- Chrome 144 and newer can offer consented automatic connection through
  `chrome://inspect/#remote-debugging`; this is distinct from launch-time
  switches and can expose all windows in the selected profile, so the explicit
  authorization boundary for everyday profiles still applies.
- Playwright MCP is a browser automation MCP that emphasizes structured
  accessibility snapshots for LLM interaction. Playwright CLI/Test remain the
  preferred durable automation and regression path after a browser issue is
  confirmed.
- Playwright browser automation best practice for agent workflows is one
  browser with isolated contexts where practical, plus explicit cleanup paths
  for `page.close()`, `context.close()`, and `browser.close()`.
- MCP is a standard protocol for connecting models to external tools and
  context; agent-specific configuration syntax is owned by each agent platform.
- Codex supports stdio MCP servers in `config.toml` under `mcp_servers`, with
  `command`, `args`, environment options, enablement, and tool policy fields.

## Supported Agent Platform Status

| Platform | Status | Notes |
|---|---|---|
| codex | source-backed | Official Codex manual documents stdio MCP `config.toml` tables and `codex mcp add`. The helper emits a Codex example. |
| claude-code | source-backed | Official Claude Code docs document MCP commands, scopes, and local stdio servers. The helper defers to docs because the official page is command/workflow-oriented. |
| cursor | source-backed | Official Cursor docs document `mcpServers` in project `.cursor/mcp.json` or global `~/.cursor/mcp.json`. The helper emits a Cursor example. |
| kilo | source-backed | Official Kilo docs document `mcp` entries with `type: "local"` and command arrays in global `~/.config/kilo/kilo.json[c]` or project `kilo.json[c]` locations. The helper emits a Kilo example. |
| opencode | source-backed | Stable OpenCode docs document `mcp` entries in global `~/.config/opencode/opencode.json[c]` or project-root `opencode.json[c]`. The helper emits the stable config shape; beta V2 uses a different schema. |
| openclaw | source-backed | Official OpenClaw docs document `mcp.servers` and canonical embedded `transport` spelling for streamable HTTP. The helper defers to docs for local stdio Chrome DevTools MCP syntax. |

## Limitations

- Package versions are volatile. The dated registry snapshot on 2026-09-04 was
  `chrome-devtools-mcp` 1.8.0, `@playwright/mcp` 0.0.80,
  `@playwright/cli` 0.1.19, and `playwright` 1.62.1. The MCP and CLI packages
  depend on a Playwright 1.63 alpha, so these dist-tags do not identify one
  shared browser-engine version.
- Chrome and MCP tool flags are volatile. Recheck Chrome DevTools MCP help or
  upstream docs before changing `--isolated`, `--userDataDir`, or
  `--pageIdRouting` guidance. The main advanced-usage page still used the stale
  experimental flag name on 2026-09-04; stable 1.8.0 source, generated config,
  and the 1.8.0 changelog control this package's guidance.
- This skill does not install, start, or configure MCP servers by itself. It
  gives agents a source-backed workflow and read-only environment inspection.
- Agent-specific MCP examples are intentionally omitted unless this skill has a
  current source-backed shape for that platform.

# MCP Bootstrap And Repair

## Detection Order

1. Check whether Chrome DevTools MCP tools are already exposed in the active
   agent. If they are usable, continue with page discovery.
2. Check the active agent's native MCP discovery surface, such as a command,
   settings view, or documented config file.
3. If a Chrome DevTools MCP profile exists, inspect whether it starts, which
   tools are enabled, and whether it uses a dedicated profile.
4. Offer bootstrap only when no usable profile exists.

## Read-Only Probe

From this skill directory:

```bash
python3 scripts/chrome_devtools_mcp_environment.py inspect --json
python3 scripts/chrome_devtools_mcp_environment.py standard-config --json
```

`inspect` reports `node`, `npx`, Chrome executable candidates, the recommended
agent-owned profile path, and warning-only host issues. Use `--require` only in
automation that should fail when host prerequisites are missing.

`standard-config` emits a client-neutral stdio MCP server definition:

```json
{
  "name": "chrome-devtools",
  "command": "npx",
  "args": [
    "-y",
    "chrome-devtools-mcp@latest",
    "--user-data-dir=.localsetup-maint/ui-browser-profiles/chrome-devtools",
    "--no-usage-statistics",
    "--no-performance-crux",
    "--redactNetworkHeaders"
  ]
}
```

Translate that definition through the active agent's current docs. Do not guess
syntax for unsupported or undocumented platforms.

## Repair Guidance

- If `node` or `npx` is missing, report that host prerequisite and stop short of
  changing system packages.
- If Chrome is missing, warn that the machine may need Chrome or an explicit
  executable/channel configured. Do not fail default inspection.
- If the active profile has `--slim`, note that some tool categories may be
  unavailable and adjust evidence collection.
- If network headers are not redacted, recommend adding
  `--redactNetworkHeaders`.
- If a user data dir points to a personal profile, recommend a dedicated
  agent-owned profile unless the user explicitly authorized reuse.
- Do not delete profiles, kill browsers, or edit existing MCP config without a
  user-approved platform-specific workflow.

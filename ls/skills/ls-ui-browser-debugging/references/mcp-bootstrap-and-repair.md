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
python3 scripts/chrome_devtools_mcp_environment.py inspect --state-root <absolute-project-root> --json
python3 scripts/chrome_devtools_mcp_environment.py standard-config --json
python3 scripts/chrome_devtools_mcp_environment.py standard-config --mode persistent --state-root <absolute-project-root> --json
```

`inspect` reports `node`, `npx`, Chrome executable candidates, the dedicated
absolute persistent agent-owned profile path resolved from `--state-root`, and
warning-only host issues. Use
`--require` only in automation that should fail when host prerequisites are
missing.

`standard-config` emits a client-neutral stdio MCP server definition. Isolated
ephemeral browser state is the default:

```json
{
  "name": "chrome-devtools",
  "mode": "isolated",
  "command": "npx",
  "args": [
    "-y",
    "chrome-devtools-mcp@latest",
    "--no-usage-statistics",
    "--no-performance-crux",
    "--redactNetworkHeaders",
    "--isolated=true"
  ]
}
```

Use persistent mode only when login or state reuse is required:

```json
{
  "name": "chrome-devtools",
  "mode": "persistent",
  "command": "npx",
  "args": [
    "-y",
    "chrome-devtools-mcp@latest",
    "--no-usage-statistics",
    "--no-performance-crux",
    "--redactNetworkHeaders",
    "--userDataDir=<absolute-project-root>/.localsetup-maint/ui-browser-profiles/chrome-devtools"
  ]
}
```

The helper requires an absolute `--state-root` for persistent output so the MCP
process working directory cannot redirect profile state. Use the same root in
the browser-session guard. Translate the definition through the active agent's
current docs. Do not guess syntax for unsupported or undocumented platforms.

## Repair Guidance

- If `node` or `npx` is missing, report that host prerequisite and stop short of
  changing system packages.
- If Chrome is missing, warn that the machine may need Chrome or an explicit
  executable/channel configured. Do not fail default inspection.
- If the active profile has `--slim`, note that some tool categories may be
  unavailable and adjust evidence collection.
- If network headers are not redacted, recommend adding
  `--redactNetworkHeaders`.
- If persistent mode points to a personal profile, recommend a dedicated
  agent-owned profile unless the user explicitly authorized reuse.
- If a profile tries to attach remote debugging to the default Chrome data
  directory, note that Chrome 136 restricts remote debugging on the default
  profile and recommend `--isolated=true` or `--userDataDir` with a non-default
  agent profile.
- Chrome 144 and newer may offer consented automatic connection through
  `chrome://inspect/#remote-debugging`; treat that as separate from launch-time
  remote-debugging switches and never attach to an everyday profile without
  explicit user authorization.
- Do not delete profiles, kill browsers, or edit existing MCP config without a
  user-approved platform-specific workflow.

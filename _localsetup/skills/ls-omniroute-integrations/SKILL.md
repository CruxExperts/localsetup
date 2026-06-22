---
name: ls-omniroute-integrations
description: OmniRoute agent protocols and runtime extension workflows for MCP, A2A, CLI tools, plugins, skills, tunnels, webhooks, and external integration diagnostics.
metadata:
  version: "1.0"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: integrations
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: v3.8.32
    source_commit: bfaf459f3c15e5260a6284eee5e9824f22a8e00d
---

# OmniRoute Integrations

Purpose: work with OmniRoute integration surfaces without loading the whole admin pack: MCP, A2A, CLI tools, plugins, skills, tunnels, webhooks, and agent bridge diagnostics.

## Start With Preflight

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py preflight \
  --required-access read
```

Use `--required-access admin` before changing tools, plugin configuration, tunnels, webhooks, or exposed protocol settings.

## Scope

Use this skill for:

- `/api/mcp/*`
- `/a2a` and `/api/a2a/*`
- `/api/cli-tools/*`
- `/api/skills/*`, `/api/agent-skills/*`, and `/api/plugins/*`
- `/api/tools/agent-bridge/*` and `/api/tools/traffic-inspector/*`
- `/api/tunnels/*`, `/api/webhooks/*`, and exposure diagnostics.

Routes that can spawn child processes or expose local services must remain local-only or explicitly protected by OmniRoute access controls. Do not make tunnel, MCP, CLI-tools, service, or webhook mutations without explicit user approval.

## Commands

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/mcp/tools
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/cli-tools
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/webhooks
```

For provider credentials, key scopes, or persistent settings behind an integration, route to `ls-omniroute-admin-automation`.

## Upstream Coverage

Covers upstream v3.8.32 skills:

- `omni-mcp`
- `omni-agents-a2a`
- `omni-cli-tools`
- `cli-mcp`
- `cli-a2a`
- `cli-plugins-skills`
- `omni-tunnels`
- `omni-webhooks`
- `cli-tunnel`

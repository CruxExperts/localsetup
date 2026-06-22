---
name: ls-omniroute-codex
description: OmniRoute client onboarding and Codex CLI configuration workflow. Use for setup, launch, Codex profile files, wire_api responses configuration, and safe agent-client registration with OmniRoute.
metadata:
  version: "1.0"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: codex-onboarding
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: v3.8.32
    source_commit: bfaf459f3c15e5260a6284eee5e9824f22a8e00d
---

# OmniRoute Codex Onboarding

Purpose: configure Codex and related agent clients to use OmniRoute safely, with current v3.8.32 setup and launch distinctions.

## Start With Preflight

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py preflight \
  --required-access runtime
```

If `OMNIROUTE_API_KEY` or `OMNIROUTE_BASE_URL` is missing, generate durable registration commands:

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py env-commands
```

Persistent shell files affect future login shells. Already-running terminals, tmux sessions, GUI apps, Codex, OpenCode, and services need a relaunch or service-manager environment update before they inherit new values.

## Scope

Use this skill for:

- OmniRoute setup and launch distinctions.
- Codex profile files under `~/.codex/<name>.config.toml`.
- Codex `wire_api = "responses"` for OmniRoute routing.
- `/api/cli-tools/codex-settings` and `/api/cli-tools/codex-profiles` checks.
- Choosing model/catalog settings from `/v1/models` and OmniRoute model metadata.
- Client registration troubleshooting when env vars, API keys, or endpoint access are missing.

Do not overwrite `~/.codex/config.toml`, shell startup files, API keys, provider settings, or model routing rules without explicit user approval. Do not present `model_max_output_tokens` as effective Codex config when upstream guidance says it is ignored.

## Commands

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /v1/models --required-access runtime
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/cli-tools/codex-settings
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/cli-tools/codex-profiles
```

Use `ls-omniroute-proxy` for model/provider catalog interpretation and `ls-omniroute-admin-automation` for persistent server-side configuration changes.

## Upstream Coverage

Covers upstream v3.8.32 skills:

- `config-codex-cli`
- `cli-setup`
- `cli-serve`

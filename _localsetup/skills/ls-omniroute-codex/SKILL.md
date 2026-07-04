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
    source_ref: main
    source_commit: 0c7f756f922fe3c0408e41852577027b496489bf
    package_version: 3.8.43
    release_package_commit: b729a8f27364f072c87082e03bb8e122f3d76251
---

# OmniRoute Codex Onboarding

Purpose: configure Codex and related agent clients to use OmniRoute safely, with current v3.8.43 setup and launch distinctions.

## Start With Preflight

```bash
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" preflight \
  --required-access runtime
```

If `OMNIROUTE_API_KEY` or `OMNIROUTE_BASE_URL` is missing, generate durable registration commands:

```bash
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" env-commands
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
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /v1/models --required-access runtime
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/cli-tools/codex-settings
python3 "$(python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/cli-tools/codex-profiles
```

Use `ls-omniroute-proxy` for model/provider catalog interpretation and `ls-omniroute-admin-automation` for persistent server-side configuration changes.

## Upstream Coverage

Covers upstream v3.8.43 skills:

- `config-codex-cli`
- `cli-setup`
- `cli-serve`

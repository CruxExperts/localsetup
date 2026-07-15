---
name: ls-omniroute
description: Main OmniRoute skill for issue resolution, environment/API-key preflight, API surface routing, and choosing the focused Localsetup OmniRoute skill or deterministic CLI path. Use whenever a task mentions OmniRoute before loading a narrower OmniRoute skill.
metadata:
  version: "1.0"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: main-router
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: main
    source_commit: 0c7f756f922fe3c0408e41852577027b496489bf
    package_version: 3.8.43
    release_package_commit: b729a8f27364f072c87082e03bb8e122f3d76251
---

# OmniRoute

Purpose: keep OmniRoute work grounded in a small Localsetup-native skill surface. Load this skill first for OmniRoute tasks, run the preflight when credentials or access may matter, then route to the narrow skill or CLI command that matches the operation.

## Start here

1. Identify the target endpoint and intended access level:
   - `runtime`: OpenAI-compatible inference and model listing.
   - `read`: health, model/provider catalogs, usage, settings reads, logs, and diagnostics.
   - `write`: configuration updates, provider changes, key rotation, routing changes, budgets, backups, and restore preparation.
   - `admin`: privileged state, key inventory, settings, provider credentials, backup/restore, and reconciliation.
2. Run a preflight before troubleshooting, registering env vars, or invoking live OmniRoute API calls:

```bash
python3 "$(python3 ls/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" preflight \
  --base-url "${OMNIROUTE_BASE_URL:-http://localhost:20128}" \
  --api-key-env OMNIROUTE_API_KEY \
  --required-access read
```

3. If env vars are missing, print durable user-level registration commands:

```bash
python3 "$(python3 ls/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" env-commands \
  --base-url "http://localhost:20128" \
  --api-key-env OMNIROUTE_API_KEY
```

The generated commands intentionally use environment variables and placeholders. They do not print or persist a real key value supplied to the running process. After writing persistent env vars, restart the terminal, tmux session, GUI app, service manager, Codex, OpenCode, or any other already-running process that must inherit them.

## Skill routing

- Use `ls-omniroute-proxy` for read-only runtime discovery: `/v1/models`, model catalogs, provider metadata, context windows, quotas, routing combos, compression discovery, MCP/A2A discovery, and agent client configuration.
- Use `ls-omniroute-admin-automation` for admin workflows: providers, API keys, aliases, combos, fallbacks, budgets, policy, backup/restore, settings, drift reconciliation, and explicit mutations.
- Use `ls-omniroute-update` for upstream version tracking, source coverage, freshness reports, and future OmniRoute skill-pack maintenance.
- Stay in this skill for first-response issue triage, env registration, access compatibility checks, and generic deterministic API probes.

## Deterministic API CLI

The bundled `omniroute_api.py` tool is the stable Localsetup CLI surface for generic OmniRoute API checks. It is intentionally conservative:

- It reads secrets only from env vars named by `--api-key-env`.
- It rejects base URLs with embedded credentials.
- It redacts authorization material from output.
- It allows `GET` requests by default.
- It requires `--allow-mutation` for `POST`, `PUT`, `PATCH`, and `DELETE`.
- It treats mutation approval as separate from access checks; approval is still required for writes to provider settings, API keys, budgets, system prompts, routing rules, Qdrant credentials, shell startup files, Codex config, or live admin state.

Examples:

```bash
python3 "$(python3 ls/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /api/monitoring/health
python3 "$(python3 ls/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request GET /v1/models --required-access runtime
python3 "$(python3 ls/tools/localsetup.py --source-root . path package ls-omniroute scripts/omniroute_api.py)" request POST /api/settings \
  --body-json '{"example": true}' \
  --required-access admin \
  --allow-mutation
```

Prefer the focused admin automation skill for planned mutations because it has snapshots, dry-run planning, audit logs, and operation-specific validation. Use the generic CLI for deterministic probes, compatibility checks, and API coverage gaps.

## v3.8.43 coverage

Localsetup intentionally consolidates OmniRoute v3.8.43 into a small native pack. The upstream repository has 43 skill documents at commit `0c7f756f922fe3c0408e41852577027b496489bf`; their coverage is tracked in `references/upstream-skill-coverage.md` rather than exposed as 43 separate Localsetup skills.

Coverage groups:

- Runtime and inference: models, chat, batches, contexts, compression, routing, resilience, cache, and cost/usage.
- Administration: auth, API keys, providers, settings, budgets, logs, backups, sync/cloud, version manager, and local services.
- Integrations: MCP, A2A, CLI tools, plugins/skills, tunnels, webhooks, proxies, and Codex CLI configuration.
- Maintenance: update workflow, source provenance, strict upstream comparison, and release notes.

## Safety defaults

- Do not log raw API keys, management cookies, provider tokens, Qdrant credentials, shell startup contents that contain secrets, or authorization headers.
- Use `OMNIROUTE_BASE_URL` and `OMNIROUTE_API_KEY` by default; allow alternate env var names only after validating that the name is a normal shell identifier.
- Keep live discovery and write operations separate. Discovery can run read-only; writes require explicit user approval and the narrow admin workflow when available.
- For Codex configuration, use `wire_api = "responses"` for OmniRoute Codex routing. Do not present `model_max_output_tokens` as effective Codex config when upstream guidance says it is ignored.

## References

- `references/upstream-skill-coverage.md`
- `scripts/omniroute_api.py`
- `../ls-omniroute-proxy/SKILL.md`
- `../ls-omniroute-admin-automation/SKILL.md`
- `../ls-omniroute-update/SKILL.md`

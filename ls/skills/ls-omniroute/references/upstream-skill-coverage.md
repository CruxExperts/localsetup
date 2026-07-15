# OmniRoute Upstream Skill Coverage

Localsetup consolidates OmniRoute v3.8.43 into a small native skill pack:

- `ls-omniroute`: always-visible main router, issue triage, env/API preflight, generic deterministic API CLI.
- `ls-omniroute-proxy`: inference, models, routing, batches, runtime discovery, provider catalogs, and agent client discovery.
- `ls-omniroute-admin-automation`: providers, auth, API keys, budgets, settings, backups, sync, service state, and guarded mutations.
- `ls-omniroute-observability`: health, usage, quota, cost, audit, policy, resilience, and evaluations.
- `ls-omniroute-context`: context engineering, compression, memory, cache, RTK, and Qdrant settings.
- `ls-omniroute-integrations`: MCP, A2A, CLI tools, plugins, skills, tunnels, webhooks, and external integration diagnostics.
- `ls-omniroute-codex`: Codex CLI onboarding, setup/launch distinction, profile files, and client registration.
- `ls-omniroute-update`: source update, provenance, and coverage maintenance.

Source pin:

- Repository: `https://github.com/diegosouzapw/OmniRoute`
- Package/release version: `v3.8.43`
- Source commit on `main`: `0c7f756f922fe3c0408e41852577027b496489bf`
- Commit date: `2026-07-03T21:16:16Z`
- Upstream skill count: `43`

## Coverage Map

| Upstream skill | Localsetup coverage |
|---|---|
| `cli-a2a` | `ls-omniroute-integrations` |
| `cli-backup-sync` | `ls-omniroute-admin-automation` |
| `cli-batches` | `ls-omniroute-proxy` |
| `cli-chat` | `ls-omniroute-proxy` |
| `cli-compression` | `ls-omniroute-context` |
| `cli-contexts` | `ls-omniroute-context` |
| `cli-cost-usage` | `ls-omniroute-observability` |
| `cli-eval` | `ls-omniroute-observability` |
| `cli-health` | `ls-omniroute-observability` |
| `cli-keys` | `ls-omniroute-admin-automation` |
| `cli-mcp` | `ls-omniroute-integrations` |
| `cli-models` | `ls-omniroute-proxy` |
| `cli-plugins-skills` | `ls-omniroute-integrations` |
| `cli-policy-audit` | `ls-omniroute-observability` |
| `cli-providers` | `ls-omniroute-admin-automation` |
| `cli-resilience` | `ls-omniroute-observability` |
| `cli-routing` | `ls-omniroute-proxy` |
| `cli-serve` | `ls-omniroute-codex` |
| `cli-setup` | `ls-omniroute-codex` |
| `cli-tunnel` | `ls-omniroute-integrations` |
| `config-codex-cli` | `ls-omniroute-codex` |
| `omni-agents-a2a` | `ls-omniroute-integrations` |
| `omni-api-keys` | `ls-omniroute-admin-automation` |
| `omni-auth` | `ls-omniroute-admin-automation` |
| `omni-budget` | `ls-omniroute-observability` |
| `omni-cache` | `ls-omniroute-context` |
| `omni-cli-tools` | `ls-omniroute-integrations` |
| `omni-combos-routing` | `ls-omniroute-proxy` |
| `omni-compression` | `ls-omniroute-context` |
| `omni-context-rtk` | `ls-omniroute-context` |
| `omni-db-backups` | `ls-omniroute-admin-automation` |
| `omni-inference` | `ls-omniroute-proxy` |
| `omni-mcp` | `ls-omniroute-integrations` |
| `omni-models` | `ls-omniroute-proxy` |
| `omni-providers` | `ls-omniroute-admin-automation` |
| `omni-proxies` | `ls-omniroute-admin-automation` |
| `omni-resilience` | `ls-omniroute-observability` |
| `omni-settings` | `ls-omniroute-admin-automation` |
| `omni-sync-cloud` | `ls-omniroute-admin-automation` |
| `omni-tunnels` | `ls-omniroute-integrations` |
| `omni-usage-logs` | `ls-omniroute-observability` |
| `omni-version-manager` | `ls-omniroute-admin-automation`, `ls-omniroute-codex` |
| `omni-webhooks` | `ls-omniroute-integrations` |

## Maintenance Rule

When updating OmniRoute, refresh this coverage map and the `NATIVE_COVERAGE` mapping in `../ls-omniroute-update/scripts/omniroute_update.py` from the pinned upstream `skills/*/SKILL.md` inventory before changing pack membership. If a future upstream skill introduces a new functional area that does not fit these native skills, add a focused native skill only after recording why the existing surfaces cannot cover it cleanly.

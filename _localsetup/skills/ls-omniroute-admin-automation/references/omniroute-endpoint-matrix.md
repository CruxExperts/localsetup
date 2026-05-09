# OmniRoute Endpoint Matrix (Administration)

## Discovery and health

| Method | Path | Auth |
|---|---|---|
| GET | /api/monitoring/health | mgmt |
| GET | /api/telemetry/summary | mgmt |
| GET | /api/system-info | mgmt |
| GET | /api/init | mgmt |
| POST | /api/restart | mgmt |
| POST | /api/shutdown | mgmt |

## Providers and nodes

| Method | Path | Auth |
|---|---|---|
| GET/POST | /api/providers | mgmt |
| GET/PUT/DELETE | /api/providers/{id} | mgmt |
| POST | /api/providers/{id}/test | mgmt |
| GET/POST/PATCH/DELETE | /api/provider-nodes | mgmt |
| GET/POST/PATCH/DELETE | /api/provider-models | mgmt |
| POST | /api/providers/validate | mgmt |

## Models and aliases

| Method | Path | Auth |
|---|---|---|
| GET | /api/models/catalog | mgmt |
| GET/POST/PATCH/DELETE | /api/models/alias | mgmt |
| GET | /api/models/openrouter-catalog | mgmt |
| GET | /v1/models | runtime |
| GET | /v1beta/models | runtime |
| GET | /api/tags | runtime |

## Routing combos and fallback chains

| Method | Path | Auth |
|---|---|---|
| GET/POST/PATCH/DELETE | /api/combos | mgmt |
| GET | /api/combos/metrics | mgmt |
| GET/POST/PATCH/DELETE | /api/fallback/chains | mgmt |

## Keys, limits, budget, resilience

| Method | Path | Auth |
|---|---|---|
| GET/POST/DELETE | /api/keys | mgmt |
| GET | /api/rate-limits | mgmt |
| GET/POST | /api/rate-limit | mgmt |
| GET/PATCH | /api/resilience | mgmt |
| POST | /api/resilience/reset | mgmt |
| GET/POST | /api/usage/budget | mgmt |

## Backup and sync

| Method | Path | Auth |
|---|---|---|
| GET/PUT/POST | /api/db-backups | mgmt |
| GET | /api/db-backups/export | mgmt |
| POST | /api/db-backups/import | mgmt |
| GET | /api/db-backups/exportAll | mgmt |
| POST | /api/sync/initialize | mgmt |
| POST | /api/sync/cloud | mgmt |
| GET/POST/DELETE | /api/sync/tokens | mgmt |
| GET | /api/sync/bundle | mgmt |

## Policies and evals

| Method | Path | Auth |
|---|---|---|
| GET/POST | /api/evals | mgmt |
| GET | /api/evals/{suiteId} | mgmt |
| GET/POST/DELETE | /api/policies | mgmt |
| GET | /api/compliance/audit-log | mgmt |

## A2A and translator

| Method | Path | Auth |
|---|---|---|
| GET | /.well-known/agent.json | public |
| POST | /a2a | mgmt |
| POST | /api/translator/detect | mgmt |
| POST | /api/translator/translate | mgmt |
| POST | /api/translator/send | mgmt |

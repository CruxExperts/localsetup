# OmniRoute Endpoint Matrix (Administration)

Routes in this matrix are current LocalSetup guidance for OmniRoute administration, but management, MCP, catalog, and health routes can vary by OmniRoute version, deployment mode, reverse proxy, and authentication configuration. When a remote deployment returns 404 for a listed management route, verify the deployed version and routing before assuming the capability is absent. Use authenticated `/v1/models` only as a runtime inventory fallback; it does not prove admin access.

## Discovery and health

| Method | Path | Auth |
|---|---|---|
| GET | /api/monitoring/health | mgmt |
| GET | /api/telemetry/summary | mgmt |
| GET | /api/init | mgmt |
| POST | /api/restart | mgmt |
| POST | /api/shutdown | mgmt |

## Providers and nodes

| Method | Path | Auth |
|---|---|---|
| GET/POST | /api/providers | mgmt |
| GET/PUT/DELETE | /api/providers/{id} | mgmt |
| POST | /api/providers/{id}/test | mgmt |
| GET/POST | /api/provider-nodes | mgmt |
| GET/POST/PATCH/DELETE | /api/provider-models | mgmt |
| POST | /api/providers/validate | mgmt |

## Models and aliases

| Method | Path | Auth |
|---|---|---|
| GET | /api/models/catalog | mgmt |
| GET/PUT/DELETE | /api/models/alias | mgmt |
| GET | /api/models/openrouter-catalog | mgmt |
| GET | /v1/models | runtime |
| GET | /v1beta/models | runtime |
| GET | /api/tags | runtime |

## Routing combos and fallback chains

| Method | Path | Auth |
|---|---|---|
| GET/POST | /api/combos | mgmt |
| GET | /api/combos/metrics | mgmt |
| GET/POST/DELETE | /api/fallback/chains | mgmt |

## Keys, limits, budget, resilience

| Method | Path | Auth |
|---|---|---|
| GET/POST | /api/keys | mgmt |
| GET | /api/rate-limits | mgmt |
| GET/POST | /api/rate-limit | mgmt |
| GET/PATCH | /api/resilience | mgmt |
| POST | /api/resilience/reset | mgmt |
| GET/POST | /api/usage/budget | mgmt |

## Settings, compression, and memory

| Method | Path | Auth |
|---|---|---|
| GET/PUT | /api/settings | mgmt |
| GET/PUT | /api/settings/compression | mgmt |
| GET/PUT | /api/settings/qdrant | mgmt |
| GET | /api/settings/qdrant/health | mgmt |
| POST | /api/settings/qdrant/search | mgmt |
| POST | /api/settings/qdrant/cleanup | mgmt |
| GET | /api/settings/qdrant/embedding-models | mgmt |

## Backup and sync

| Method | Path | Auth |
|---|---|---|
| GET/PUT/POST | /api/db-backups | mgmt |
| GET | /api/db-backups/export | mgmt |
| POST | /api/db-backups/import | mgmt |
| GET | /api/db-backups/exportAll | mgmt |
| POST | /api/sync/initialize | mgmt |
| POST | /api/sync/cloud | mgmt |
| GET/POST | /api/sync/tokens | mgmt |
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

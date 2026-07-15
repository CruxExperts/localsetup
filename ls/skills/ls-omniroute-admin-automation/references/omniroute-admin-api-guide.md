# OmniRoute Administration API Guide

---
title: "OmniRoute v3.8.43 Administration API Guide"
category: reference
status: ACTIVE
last_updated: "2026-07-04"
tags: [omniroute, api, administration, proxy, routing, budget, resilience, automation]
---

## 1. Overview

OmniRoute is an open-source AI gateway written in TypeScript/Next.js that presents OpenAI-compatible `/v1/*` endpoints and routes traffic across many providers. Version `3.8.43` includes routing combos, fallback chains, quota tracking, resilience controls, cloud sync, compression settings, optional memory/Qdrant support, and rich management APIs.

This guide focuses on full administration through `/api/*` endpoints.

## 2. Authentication Model

OmniRoute typically uses two auth domains:

- Runtime access for `/v1/*` model calls.
- Management access for `/api/*` administration calls.

Important behavior:

- Runtime key and management token can be different credentials.
- Passing a runtime key to admin endpoints can return errors such as invalid management token.

### Recommended credential handling

- Use environment variables only.
- Never embed secrets in files, scripts, or commit history.
- Rotate keys through `/api/keys` workflows.
- Run `python3 scripts/omniroute_admin.py preflight --required-access read` from inside the installed package directory before admin automation. From a Localsetup repo root, resolve the helper with `python3 ls/tools/localsetup.py --source-root . path package ls-omniroute-admin-automation scripts/omniroute_admin.py`. Use `write` or `admin` for workflows that need stronger endpoint access.

## 3. Endpoint Inventory (high-level)

### System and health

- `GET /api/monitoring/health`
- `GET /api/telemetry/summary`
- `GET /api/system-info`
- `POST /api/restart`
- `POST /api/shutdown`

### Providers and nodes

- `GET/POST /api/providers`
- `GET/PUT/DELETE /api/providers/{id}`
- `POST /api/providers/{id}/test`
- `GET/POST/PATCH/DELETE /api/provider-nodes`
- `GET/POST/PATCH/DELETE /api/provider-models`

### Catalog, models, aliases

- `GET /api/models/catalog`
- `GET/POST/PATCH/DELETE /api/models/alias`
- `GET /v1/models`
- `GET /v1beta/models`
- `GET /api/tags`

### Routing and fallback

- `GET/POST/PATCH/DELETE /api/combos`
- `GET /api/combos/metrics`
- `GET/POST/PATCH/DELETE /api/fallback/chains`

### Keys, limits, budget, resilience

- `GET/POST/DELETE /api/keys`
- `GET/POST /api/rate-limit`
- `GET /api/rate-limits`
- `GET/PATCH /api/resilience`
- `POST /api/resilience/reset`
- `GET/POST /api/usage/budget`

### Backup and sync

- `GET/PUT/POST /api/db-backups`
- `GET /api/db-backups/export`
- `POST /api/db-backups/import`
- `GET /api/db-backups/exportAll`
- `POST /api/sync/initialize`
- `POST /api/sync/cloud`
- `GET/POST/DELETE /api/sync/tokens`
- `GET /api/sync/bundle`

### Policies, evals, compliance

- `GET/POST /api/evals`
- `GET /api/evals/{suiteId}`
- `GET/POST/DELETE /api/policies`
- `GET /api/compliance/audit-log`

### A2A and translator

- `GET /.well-known/agent.json`
- `POST /a2a`
- `POST /api/translator/detect`
- `POST /api/translator/translate`
- `POST /api/translator/send`

## 4. Request and Response Conventions

### Useful request headers

- `X-OmniRoute-No-Cache: true`
- `X-OmniRoute-Progress: true`
- `X-Session-Id: <id>`
- `Idempotency-Key: <id>`

### Useful response headers

- `X-OmniRoute-Cache: HIT|MISS`
- `X-OmniRoute-Idempotent: true`
- `X-OmniRoute-Progress: enabled`
- `X-OmniRoute-Session-Id: <id>`

## 5. Safe Plan and Apply Workflow

Use a 3-step mutation model:

1) Snapshot current state.
2) Build and review a plan.
3) Apply with explicit confirmation.

Example commands:

```bash
python3 scripts/omniroute_admin.py snapshot --out state/live.json
python3 scripts/omniroute_admin.py plan --desired manifests/prod.json --out state/plan.json
python3 scripts/omniroute_admin.py apply --plan state/plan.json --yes
```

These examples assume the installed package directory as the current working directory.

For destructive operations, require both:

- `--yes`
- `--allow-destructive`

## 6. Python Automation Quick Start

```python
import os
from scripts.lib.omniroute_admin.client import OmniRouteAdminClient

client = OmniRouteAdminClient(
    base_url=os.environ.get("OMNIROUTE_BASE_URL", "http://localhost:20128"),
    api_key=os.environ.get("OMNIROUTE_API_KEY"),
    management_cookie=os.environ.get("OMNIROUTE_MGMT_COOKIE"),
)

health = client.health()
print(health.get("status"))
```

## 7. Error Handling Guidance

Common status codes:

- `400` validation error
- `401` missing/invalid auth
- `403` token valid but not authorized
- `404` missing resource
- `409` conflict
- `422` semantic validation failure
- `500` server/internal failure

Retry only transient failures (429/5xx/timeouts), not permanent validation/auth errors.

## 8. Compact Endpoint Matrix

See: `references/omniroute-endpoint-matrix.md`

## 9. Automation Runbook

See: `references/omniroute-automation-runbook.md`

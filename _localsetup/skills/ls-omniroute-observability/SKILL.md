---
name: ls-omniroute-observability
description: OmniRoute observability, usage, quota, resilience, health, policy, audit, and evaluation workflows. Use for monitoring, troubleshooting, cost reports, quota/rate-limit checks, circuit breakers, provider metrics, logs, and non-mutating diagnostics.
metadata:
  version: "1.0"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: observability
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: v3.8.32
    source_commit: bfaf459f3c15e5260a6284eee5e9824f22a8e00d
---

# OmniRoute Observability

Purpose: inspect OmniRoute health, usage, quota, cost, resilience, policy, audit, and evaluation state without mutating live configuration.

## Start With Preflight

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py preflight \
  --required-access read \
  --fail-on-incompatible
```

Use `ls-omniroute` first if env vars or access are uncertain. Do not paste keys into commands; use `OMNIROUTE_API_KEY` or another validated env var name.

## Scope

Use this skill for:

- `/api/monitoring/health`, provider health, latency, circuit breakers, cooldowns, and resilience checks.
- `/api/usage/*`, token/cost breakdowns, usage logs, call logs, and analytics.
- `/api/quota/*`, `/api/rate-limit*`, budgets, provider quotas, and rate-limit diagnostics.
- `/api/compliance/audit-log`, policy/audit review, and security event inspection.
- `/api/evals` and benchmark/evaluation status.

Do not use this skill for provider/key mutations, budget writes, or policy changes. Route those to `ls-omniroute-admin-automation` after explicit approval.

## Commands

```bash
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/monitoring/health
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/usage/summary
python3 _localsetup/skills/ls-omniroute/scripts/omniroute_api.py request GET /api/provider-metrics
```

If an endpoint is deployment-specific, inspect the current OmniRoute version and route list first rather than guessing. Treat 401/403 as an access mismatch and rerun preflight with the intended access level.

## Upstream Coverage

Covers upstream v3.8.32 skills:

- `omni-budget`
- `omni-usage-logs`
- `omni-resilience`
- `cli-cost-usage`
- `cli-resilience`
- `cli-health`
- `cli-policy-audit`
- `cli-eval`

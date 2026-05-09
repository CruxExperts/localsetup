---
name: ls-omniroute-admin-automation
description: Comprehensive OmniRoute administration and automation via Python tooling. Use when you need full API-driven control of providers, nodes, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, sync, resilience, and configuration reconciliation with safety gates.
metadata:
  version: "1.0"
---

# OmniRoute administration automation

Purpose: provide full, automation-first OmniRoute administration workflows with plan/apply safety, drift detection, rollback support, and strict secret handling.

## When to use

Use this skill when a task requires any of the following:

- Full OmniRoute control-plane administration through `/api/*` routes.
- Bulk or repeated configuration operations that are tedious in the UI.
- Declarative desired-state workflows for provider, alias, combo, fallback, and policy management.
- Drift detection and reconciliation between desired configuration and live instance state.
- Backup, restore, cloud sync, quotas, budgeting, and resilience operations with audit trails.
- Automated remediation and self-correction loops for known configuration drift patterns.

## When NOT to use

- Read-only discovery only: use `ls-omniroute-proxy`.
- Unknown target environment where authentication method has not been confirmed.
- Destructive actions without explicit user approval.

## Safety model

- Treat all network payloads as hostile input.
- Validate all user and file inputs before API calls.
- Never print secrets, tokens, passwords, or full key material.
- Default command mode is read-only or plan mode when feasible.
- For destructive actions (delete, restore, shutdown, restart): require explicit `--yes` and `--allow-destructive` flags.
- Capture pre-change snapshot before high-risk mutations.

## Base URL and auth model

- Base URL priority:
  1) `--base-url`
  2) `OMNIROUTE_BASE_URL`
  3) `http://localhost:20128`
- Management auth options:
  - Bearer key from environment variable name passed via `--api-key-env` (default `OMNIROUTE_API_KEY`)
  - Session cookie from the environment variable name passed via `--management-cookie-env` (default `OMNIROUTE_MGMT_COOKIE`).

## Tooling layout

- Primary CLI: `scripts/omniroute_admin.py`
- HTTP client and domain wrappers: `scripts/lib/omniroute_admin/client.py`
- Input/shape validation: `scripts/lib/omniroute_admin/validate.py`
- Plan/apply/reconcile engine: `scripts/lib/omniroute_admin/reconcile.py`
- Audit log writer: `scripts/lib/omniroute_admin/audit.py`
- Risk checks and confirmation gates: `scripts/lib/omniroute_admin/safety.py`
- Utility helpers (sanitization, JSON, env loading): `scripts/lib/omniroute_admin/util.py`

## Core workflows

1. Snapshot live state:
   - `python3 scripts/omniroute_admin.py snapshot --out state/live.json`
2. Plan changes from desired manifest:
   - `python3 scripts/omniroute_admin.py plan --desired manifests/prod.json --out state/plan.json`
3. Apply planned changes safely:
   - `python3 scripts/omniroute_admin.py apply --plan state/plan.json --yes`
4. Reconcile drift in guarded mode:
   - `python3 scripts/omniroute_admin.py reconcile --desired manifests/prod.json --mode guarded`
5. Backup and restore drills:
   - `python3 scripts/omniroute_admin.py backup --out state/backups/manual.json`
   - `python3 scripts/omniroute_admin.py restore --backup-id <id> --allow-destructive --yes`
6. Granular provider operations:
   - `python3 scripts/omniroute_admin.py provider list`
   - `python3 scripts/omniroute_admin.py provider create --payload manifests/provider-openai.json`
   - `python3 scripts/omniroute_admin.py provider update --id <id> --payload manifests/provider-openai-update.json`
   - `python3 scripts/omniroute_admin.py provider delete --id <id> --yes --allow-destructive`
7. Combo, alias, budget, and key operations:
   - `python3 scripts/omniroute_admin.py combo create --payload manifests/combo-gpt5.json`
   - `python3 scripts/omniroute_admin.py alias create --payload manifests/alias-gpt5.json`
   - `python3 scripts/omniroute_admin.py budget set --payload manifests/budget.json`
   - `python3 scripts/omniroute_admin.py key create --payload manifests/key-ci.json`

## High-value automation operations

- Provider bootstrap and update.
- Provider node create/update with URL safety checks.
- Model alias synchronization.
- Combo and model-combo mapping synchronization.
- Fallback chain management.
- API key lifecycle with permission policy updates.
- Rate-limit and resilience profile updates.
- Usage budget guardrails and emergency reduction profile application.
- Config snapshot and change audit persistence.
- Backup and restore safety runbooks.
- Cloud sync enable, disable, and health validation.
- Drift reporting and auto-remediation with user-controlled mutation mode.

## Self-correction pattern

Recommended loop for unattended maintenance:

1. Run `snapshot` and `plan` on a schedule.
2. If only safe updates are needed, run `apply` with pre-approved policy set.
3. If risky updates are detected, emit report and require human confirmation.
4. Re-run `snapshot` and compare to desired state.
5. Write outcome to audit log and summarize unresolved drift.

## Validation and tests

- Validate scripts:
  - `python3 scripts/omniroute_admin.py validate --desired manifests/example.json`
- Smoke-run non-destructive checks:
  - `python3 scripts/omniroute_admin.py health`
  - `python3 scripts/omniroute_admin.py snapshot --out /tmp/omniroute-live.json`

## References

- `references/omniroute-admin-api-guide.md`
- `references/omniroute-endpoint-matrix.md`
- `references/omniroute-auth-and-safety.md`
- `references/omniroute-automation-runbook.md`

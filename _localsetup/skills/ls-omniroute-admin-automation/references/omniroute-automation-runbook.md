# OmniRoute Automation Runbook

This runbook provides practical step-by-step operations using `scripts/omniroute_admin.py` from inside the installed `ls-omniroute-admin-automation` package directory. From a Localsetup repo root, resolve the helper first with `python3 _localsetup/tools/localsetup.py --source-root . path package ls-omniroute-admin-automation scripts/omniroute_admin.py`.

## 1) Health check

```bash
python3 scripts/omniroute_admin.py health --base-url http://localhost:20128
```

## 2) Snapshot live state

```bash
python3 scripts/omniroute_admin.py snapshot --out state/live.json
```

## 3) Validate desired manifest

```bash
python3 scripts/omniroute_admin.py validate --desired manifests/prod.json
```

## 4) Build plan

```bash
python3 scripts/omniroute_admin.py plan --desired manifests/prod.json --out state/plan.json
```

## 5) Apply plan (non-destructive)

```bash
python3 scripts/omniroute_admin.py apply --plan state/plan.json --yes
```

## 6) Reconcile (report only)

```bash
python3 scripts/omniroute_admin.py reconcile --desired manifests/prod.json --mode report --out state/plan-report.json
```

## 7) Reconcile (guarded)

```bash
python3 scripts/omniroute_admin.py reconcile --desired manifests/prod.json --mode guarded --yes
```

Expected guarded semantics:

- Applies non-destructive operations.
- Skips destructive delete operations.
- Returns `status: "partial_success"` when only destructive operations are skipped.
- Returns `status: "failed"` only when operation errors occur.

## 8) Reconcile (enforce, destructive allowed)

```bash
python3 scripts/omniroute_admin.py reconcile --desired manifests/prod.json --mode enforce --yes --allow-destructive
```

## 9) Create backup

```bash
python3 scripts/omniroute_admin.py backup --out state/backups/manual.json
```

## 10) Restore backup (destructive)

```bash
python3 scripts/omniroute_admin.py restore --backup-id <backup-id> --yes --allow-destructive
```

## 11) Environment variables

```bash
export OMNIROUTE_BASE_URL="http://localhost:20128"
export OMNIROUTE_API_KEY="<management-or-runtime-key-as-required>"
export OMNIROUTE_MGMT_COOKIE="auth_token=<value>"  # optional cookie mode
```

## 12) Operational checklist

Before mutation:

1. Confirm endpoint auth mode.
2. Take snapshot.
3. Review plan summary.
4. Confirm destructive scope if any.

After mutation:

1. Re-run health check.
2. Re-run snapshot.
3. Compare drift against desired.
4. Archive audit log.

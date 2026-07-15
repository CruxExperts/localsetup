---
name: ls-cloudflare-dns
description: Manage Cloudflare DNS records and zone DNS settings with a Python-first direct Cloudflare v4 REST API CLI, deterministic JSON output, snapshots, dry-run plans, and apply safety gates.
metadata:
  version: "2.0"
compatibility: "Python 3.12+ with requests and jsonschema from the Localsetup uv project environment. Uses Cloudflare v4 REST API directly; no external DNS CLI dependency."
---

# Cloudflare DNS management

## Purpose

Use this skill when an agent needs to inspect, plan, or apply Cloudflare DNS changes from the terminal. The bundled `scripts/cf_dns.py` helper calls the Cloudflare v4 REST API directly, emits deterministic JSON by default, and keeps mutations behind dry-run plans, confirmation phrases, and plan hashes.

This skill is DNS-focused. Keep DNSSEC, Registrar, Workers, Pages, WAF, Zero Trust, R2, D1, and unrelated Cloudflare products out of direct tooling scope unless they are needed as adjacent DNS troubleshooting context.

## When to use

- Add, update, delete, upsert, import, export, or batch-plan DNS records.
- List zones or resolve a zone name to exactly one visible zone.
- Inspect or patch zone DNS settings or general zone settings.
- Create DNS snapshots, compare snapshots, or compare a saved plan to live DNS state.
- Run a safe Cloudflare DNS survey before Nginx Proxy Manager or server routing work.

## Tooling

Run from this skill directory:

```bash
python3 scripts/cf_dns.py --help
python3 scripts/cf_dns.py auth verify
python3 scripts/cf_dns.py zones list --all
python3 scripts/cf_dns.py records list example.com
python3 scripts/cf_dns.py records create example.com --type A --name app.example.com --content 192.0.2.10
```

The helper accepts `--api-base` for mock servers and tests. JSON output is the default; `--output table` is available for simple list views.

## Authentication

Set a scoped Cloudflare API token in the environment:

```bash
export CLOUDFLARE_API_TOKEN=...
```

`CF_API_TOKEN` is accepted as a compatibility fallback. Do not use global API keys. The helper never prints token values, Authorization headers, environment values, or credential file contents.

Minimum recommended scopes:

- Read-only inspection: `Zone:Zone:Read` and `Zone:DNS:Read`.
- DNS mutations: add `Zone:DNS:Edit` for the specific zones.
- DNS settings changes: add only the DNS settings permission needed for the target account or zone.

See `references/auth-permissions.md` for token setup and validation notes.

## Command Map

- `auth verify`: verify token validity through `/user/tokens/verify`.
- `permissions summarize`: print local guidance for minimum recommended scopes.
- `zones list|get|create|edit|delete|activation-check`: manage zone-level operations.
- `dns-settings get|patch`: use `/zones/{zone_id}/dns_settings`.
- `zone-settings list|get|patch`: use `/zones/{zone_id}/settings` and `/settings/{setting_id}`.
- `records list|find|get|create|create-json|patch|put|delete|upsert|export|import|batch-plan|batch-apply`: manage DNS records.
- `records scan trigger|list|review`: call the current DNS scan endpoints.
- `snapshot create|create-all|diff`: capture and compare normalized DNS record snapshots.
- `plan diff-live`: compare a plan's recorded live state hash with current Cloudflare DNS state.

Endpoint coverage and source links are in `references/api-scope.md`.

## Safety Rules

Mutations default to dry-run. A dry-run emits a canonical plan with `plan_hash`; applying the mutation requires:

1. `--apply`.
2. The exact confirmation phrase for the operation.
3. `--plan-hash <hash>` from the dry-run plan when the command requires a plan hash.
4. A live fetch before destructive operations when a current record or setting exists.

Confirmation phrases:

- General create/edit/update/import/batch apply: `confirm apply`.
- Deletes: `confirm delete`.
- Full record `PUT` overwrite: `confirm overwrite`.
- DNS or zone settings patch: `confirm settings`.

If the user gives a vague confirmation such as "yes" or "ok", do not apply. Re-run or show the dry-run plan and ask for the exact phrase.

## Zone Resolution

Always pass a zone explicitly. A zone ID is accepted directly. A zone name must resolve to exactly one visible Cloudflare zone. Ambiguous zone names return exit code `6` with candidate IDs; the agent must ask the user or choose an explicit ID from evidence.

## Output Contract

The CLI output is JSON by default and follows `schemas/cli-output.schema.json`:

```json
{
  "ok": true,
  "command": "records list",
  "result": [],
  "errors": [],
  "messages": [],
  "rate_limit": {}
}
```

Cloudflare v4 envelopes are preserved where useful: `success`, `errors`, `messages`, `result`, and `result_info`. The helper normalizes rate limit headers from `Ratelimit`, `Ratelimit-Policy`, and `retry-after`.

Normalized records preserve unknown Cloudflare fields in `provider_fields` so new API fields do not require immediate wrapper changes.

## References

- `references/source-ledger.md` - source freshness and unverified live-behavior notes.
- `references/api-scope.md` - supported API endpoints and out-of-scope products.
- `references/auth-permissions.md` - token setup, verification, and permission guidance.
- `references/deterministic-tooling.md` - JSON output, plan hashing, and schema contracts.
- `references/zones.md` - zone operations and activation checks.
- `references/dns-records.md` - record operations, normalization, and record ID rules.
- `references/dns-settings.md` - DNS settings and zone settings.
- `references/batch-import-export-scan.md` - batch, import/export, and scan workflows.
- `references/record-types.md` - record type notes and high-risk categories.
- `references/safety.md` - mutation gates and confirmation policy.
- `references/snapshots-plans.md` - snapshot and plan workflows.
- `references/dynamic-dns.md` - safe dynamic DNS pattern.
- `references/troubleshooting.md` - common failures and exit codes.
- `references/examples.md` - copy/paste examples.
- `references/update-procedure.md` - how to refresh schema/source evidence.

## Validation

```bash
uv run --locked python scripts/cf_dns.py --help
uv run --locked python scripts/validate_cf_dns_skill.py
uv run --locked pytest tests -q
```

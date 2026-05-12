# Deterministic tooling

`scripts/cf_dns.py` defaults to JSON and stable key ordering. JSON outputs are intended for agents, tests, and audit logs.

The CLI output schema lives at `schemas/cli-output.schema.json`.

Plan hashes are SHA-256 hashes over canonical JSON with sorted keys and compact separators. If a mutation supports `--plan-hash`, generate the dry-run plan first, review it, then pass the exact hash into the apply command.

Unknown Cloudflare DNS record fields are preserved in normalized output under `provider_fields`. This prevents accidental data loss when Cloudflare adds new fields.

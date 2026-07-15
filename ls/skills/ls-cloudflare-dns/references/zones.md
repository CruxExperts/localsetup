# Zones

Use `zones list` to inspect visible zones. Use `zones get <zone>` to resolve a zone ID or name.

Rules:

- Never assume a default zone.
- Prefer explicit zone IDs for automation.
- A zone name must resolve to exactly one visible zone.
- Ambiguous names exit with code `6` and candidate IDs.

Mutation commands:

```bash
python3 scripts/cf_dns.py zones create --account-id <account> --name example.com
python3 scripts/cf_dns.py zones edit <zone-id> --paused
python3 scripts/cf_dns.py zones delete <zone-id>
```

Create/edit/delete default to dry-run. Apply only with the required phrase and matching plan hash.

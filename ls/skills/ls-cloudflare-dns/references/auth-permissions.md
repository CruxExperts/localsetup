# Authentication and permissions

Use a scoped Cloudflare API token.

Environment lookup order:

1. `CLOUDFLARE_API_TOKEN`
2. `CF_API_TOKEN`

Run:

```bash
python3 scripts/cf_dns.py auth verify
python3 scripts/cf_dns.py permissions summarize
```

Recommended permissions:

- Read zones: `Zone:Zone:Read`.
- Read DNS records: `Zone:DNS:Read`.
- Apply DNS record mutations: `Zone:DNS:Edit`.
- Patch DNS settings: add only the setting-specific permission required by Cloudflare for the target operation.

Limit tokens to the required account and zones. Prefer IP restrictions when the host has a stable egress address. Do not write tokens into repo files, shell history, command arguments, reports, snapshots, or ledgers.

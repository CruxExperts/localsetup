# DNS settings and zone settings

DNS settings:

```bash
python3 scripts/cf_dns.py dns-settings get example.com
python3 scripts/cf_dns.py dns-settings patch example.com --json dns-settings-change.json
```

General zone settings:

```bash
python3 scripts/cf_dns.py zone-settings list example.com
python3 scripts/cf_dns.py zone-settings get example.com ipv6
python3 scripts/cf_dns.py zone-settings patch example.com ipv6 --json setting-change.json
```

Settings mutations require a live current-state fetch, dry-run plan, `confirm settings`, and matching plan hash.

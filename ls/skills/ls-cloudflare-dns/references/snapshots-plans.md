# Snapshots and plans

Create a snapshot before risky changes:

```bash
python3 scripts/cf_dns.py snapshot create example.com > snapshot.json
python3 scripts/cf_dns.py snapshot create-all > all-zones-snapshot.json
```

Compare snapshots:

```bash
python3 scripts/cf_dns.py snapshot diff before.json after.json
```

Compare a plan to live state:

```bash
python3 scripts/cf_dns.py plan diff-live example.com --plan plan.json
```

Store snapshots outside the repo unless they are sanitized fixtures. Snapshots can contain hostnames, record IDs, comments, and routing details.

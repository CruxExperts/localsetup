# DNS records

Read commands:

```bash
python3 scripts/cf_dns.py records list example.com
python3 scripts/cf_dns.py records find example.com --type A --name app.example.com
python3 scripts/cf_dns.py records get example.com <record-id>
```

Mutation commands:

```bash
python3 scripts/cf_dns.py records create example.com --type A --name app.example.com --content 192.0.2.10
python3 scripts/cf_dns.py records patch example.com <record-id> --json change.json
python3 scripts/cf_dns.py records put example.com <record-id> --json full-record.json
python3 scripts/cf_dns.py records delete example.com <record-id>
python3 scripts/cf_dns.py records upsert example.com --type A --name app.example.com --content 192.0.2.10
```

Record IDs must be fetched live before modify or delete. Do not reuse IDs from memory when applying a change.

`put` is a full overwrite and requires `confirm overwrite`. Prefer `patch` for targeted edits.

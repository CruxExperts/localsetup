# Examples

Verify token:

```bash
python3 scripts/cf_dns.py auth verify
```

List records:

```bash
python3 scripts/cf_dns.py records list example.com
```

Create a dry-run plan:

```bash
python3 scripts/cf_dns.py records create example.com --type A --name app.example.com --content 192.0.2.10
```

Apply after reviewing the dry-run plan:

```bash
python3 scripts/cf_dns.py records create example.com --type A --name app.example.com --content 192.0.2.10 --apply --confirm "confirm apply" --plan-hash <hash>
```

Delete after live fetch and dry-run:

```bash
python3 scripts/cf_dns.py records delete example.com <record-id>
python3 scripts/cf_dns.py records delete example.com <record-id> --apply --confirm "confirm delete" --plan-hash <hash>
```

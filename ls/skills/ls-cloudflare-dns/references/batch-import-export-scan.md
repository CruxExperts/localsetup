# Batch, import, export, and scan

Batch workflow:

```bash
python3 scripts/cf_dns.py records batch-plan example.com --json batch.json
python3 scripts/cf_dns.py records batch-apply example.com --json batch.json --apply --confirm "confirm apply" --plan-hash <hash>
```

Import/export:

```bash
python3 scripts/cf_dns.py records export example.com
python3 scripts/cf_dns.py records import example.com --file zonefile.txt
```

Scan:

```bash
python3 scripts/cf_dns.py records scan trigger example.com
python3 scripts/cf_dns.py records scan list example.com
python3 scripts/cf_dns.py records scan review example.com --json review.json
python3 scripts/cf_dns.py records scan review example.com --json review.json --apply --confirm "confirm apply" --plan-hash <hash>
```

Batch apply, import, and scan review are high-risk operations. Capture a snapshot first unless the user explicitly waives the snapshot in the command and the ledger records why. Scan review emits a dry-run plan by default because accepting scanned records adds records and rejecting scanned records removes candidates from the scan review set.

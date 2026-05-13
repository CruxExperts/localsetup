# Update procedure

1. Refresh source evidence from Cloudflare docs and OpenAPI.
2. Run:

```bash
python3 scripts/refresh_cloudflare_dns_schema.py
python3 scripts/validate_cf_dns_skill.py
python3 -m pytest tests -q
```

3. Update `references/source-ledger.md` with the date and any live validation status.
4. Refresh repo generated docs from the repo root:

```bash
python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .
python3 _localsetup/tools/localsetup_v3.py --source-root . generate-docs
```

5. Run catalog and framework validation before publishing.

# Update procedure

1. Refresh source evidence from Cloudflare docs and OpenAPI.
2. Run:

```bash
uv run --locked python scripts/refresh_cloudflare_dns_schema.py
uv run --locked python scripts/validate_cf_dns_skill.py
uv run --locked pytest tests -q
```

3. Update `references/source-ledger.md` with the date and any live validation status.
4. Refresh repo generated docs from the repo root:

```bash
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup_v3.py --source-root . generate-docs
```

5. Run catalog and framework validation before publishing.

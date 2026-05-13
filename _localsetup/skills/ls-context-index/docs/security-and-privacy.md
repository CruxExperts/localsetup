# Security And Privacy

The context index is sensitive derived state. Treat it like cached source content and operational metadata.

## Default Excludes

The default inventory excludes common noise and secret-bearing paths:

- `.git/`, `.venv/`, `venv/`, `node_modules/`, cache/build/dist/coverage folders, `__pycache__/`, `.pytest_cache/`
- `.localsetup/context-index/`, `_localsetup/.cache/`, `_localsetup/logs/`, local maintenance/state folders
- `*.log`, `.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.kdbx`
- path names containing `secret`, `credential`, or `token`

Maintainers can inspect exclusions with:

```bash
localsetup context-index inventory --scope repo --show-excludes
```

## Secret Policy

- Do not resolve secret aliases during indexing.
- Do not index vault files, private keys, token stores, `.env` files, or credential dumps.
- It is acceptable to index intentional alias names such as `secret_ref: cloudflare_api_token` when they are already present in documentation.
- Logs and memory usage reasons must not contain raw secrets.

## Network Policy

Search and ingest are local by default. The default embedding provider is deterministic `local_hash`, not a cloud embedding API. OpenAI-compatible HTTP providers, including local llama.cpp-style embedding servers, require explicit endpoint configuration and must not be enabled for private repos unless the operator approves the data boundary.

## Reset And Rebuild

Reset and rebuild commands delete derived index rows for the selected context and then re-ingest from files. This is safe because the database is not source of truth, but managed environments should still require explicit operator intent.

## Privacy Boundary

Repo scope stays in the repo DB by default. Framework and global/user memory share the global DB but remain segregated by `context_key`.

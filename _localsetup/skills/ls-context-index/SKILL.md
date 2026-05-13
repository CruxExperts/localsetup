---
name: ls-context-index
description: Build and query the Localsetup context index with vector-first SQLite RAG, deterministic freshness/worklist surfaces, and agent-preflight checks.
metadata:
  version: "0.1"
---

# Context Index

Use this skill when an agent needs fast Localsetup context retrieval across repo, framework, or global/user memory sources. The index is a retrieval cache; files remain the source of truth.

## Required Agent Flow

1. Run `context-index agent-preflight --scope <scope>` or `context-index freshness --scope <scope>`.
2. If `read_direct_paths` is non-empty, read those files directly before trusting search results for those paths.
3. Use `context-index search "query" --scope repo --top-k 10` for fresh indexed context.
4. Use `lookup --chunk-id UUID` before relying on a specific result.
5. Use `worker nudge` or `refresh` when the worklist has pending items.
6. Use `rebuild plan` and `rebuild apply --plan PLAN_ID` only when a reset/reindex is appropriate.

## Commands

```bash
localsetup context-index doctor
localsetup context-index agent-preflight --scope repo
localsetup context-index freshness --scope repo
localsetup context-index worklist --scope repo
localsetup context-index stats --scope repo
localsetup context-index ingest --scope repo
localsetup context-index search "how are workflows registered" --scope repo --top-k 10
localsetup context-index lookup --chunk-id UUID
localsetup context-index worker nudge --scope repo
localsetup context-index vector-rebuild plan --scope repo
localsetup context-index prune plan --scope repo
```

## Scope Model

- `repo`: repo-local docs, code, workflows, `.agentlens`, memory, and selected structured files in the repo DB by default.
- `framework`: Localsetup docs, skills, workflows, and generated catalogs in the global DB.
- `global`: user/global memory and selected global context in the same global DB as framework, segregated by `context_key`.

Every table uses UUIDv7 row IDs plus context identity columns so repo DBs can later be merged into one central SQLite or PostgreSQL database without losing scope separation.

## Security Rules

Do not request secret values from the index. Default inventory excludes `.env`, key, certificate, KeePass `.kdbx`, token, credential, secret-looking, log, cache, build, venv, and dependency folders. Secret aliases intentionally present in documentation may be indexed, but resolved values must not be.

## Important Docs

- [README](README.md)
- [Architecture](docs/architecture.md)
- [Agent Usage](docs/agent-usage.md)
- [Security And Privacy](docs/security-and-privacy.md)
- [Memory Curation](docs/memory-curation.md)
- [Platform Evaluation](docs/platform-evaluation.md)
- [Source Ledger](docs/source-ledger.md)
- [Config Schema](schemas/config.schema.json)

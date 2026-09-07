---
name: ls-context-index
description: Use when building, querying, or refreshing the LocalSetup context index with hybrid SQLite retrieval, deterministic freshness/worklist surfaces, and agent-preflight checks.
metadata:
  version: "0.1"
---

# Context Index

Use this skill when an agent needs fast LocalSetup context retrieval across repo or framework sources. The index is a retrieval cache; files remain the source of truth.

## Required Agent Flow

1. Run `context-index agent-preflight --scope <scope>` or `context-index freshness --scope <scope>`.
2. If `read_direct_paths` is non-empty, read those files directly before trusting search results for those paths.
3. Use `context-index search "query" --scope repo --top-k 10` for fresh indexed context.
4. Use `lookup --chunk-id UUID` before relying on a specific result.
5. Use `worker nudge` or `refresh` when the worklist has pending items.
6. Use plan/apply operations only after reviewing the plan JSON and passing its returned `plan_id` to apply as `--plan "<REVIEWED_PLAN_ID>"`.

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

## Query Contract

Before retrieval, validate configuration and scope, confirm privacy exclusions are active, and interpret `safe_to_use_index`, `read_direct_paths`, and the worklist rather than relying on top-level `ok` alone. Search results must identify the selected scope/context, path, line range, chunk ID, source and chunk hashes, and freshness state. Use `lookup` and then read the source file directly before exact edits or citations.

## Refresh Contract

Choose lifecycle actions from observed freshness and worklist state: no work means no-op; changed or unindexed paths use refresh/worker execution; embedding-only drift uses vector rebuild; a contaminated or explicitly clean index uses rebuild; tombstoned sources use prune. `worker nudge` only queues eligible work. After any action, rerun preflight, freshness, or worklist and retain the input, selected action, command JSON, and verification JSON as decision evidence.

## Scope Model

- `repo`: repo-local docs, code, workflows, `.agentlens`, and selected structured files in the repo DB by default.
- `framework`: LocalSetup docs, skills, workflows, and generated catalogs in the global DB.

Every table uses UUIDv7 row IDs plus context identity columns so repo DBs can later be merged into one central SQLite or PostgreSQL database without losing scope separation.

## Security Rules

Do not request secret values from the index. Default inventory excludes `.env`, key, certificate, KeePass `.kdbx`, token, credential, secret-looking, log, cache, build, venv, and dependency folders. Secret aliases intentionally present in documentation may be indexed, but resolved values must not be.

## Important Docs

- [README](README.md)
- [Architecture](docs/architecture.md)
- [Agent Usage](docs/agent-usage.md)
- [Security And Privacy](docs/security-and-privacy.md)
- [Platform Evaluation](docs/platform-evaluation.md)
- [Source Ledger](docs/source-ledger.md)
- [Config Schema](schemas/config.schema.json)

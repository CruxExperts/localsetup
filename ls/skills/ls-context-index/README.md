# ls-context-index

`ls-context-index` is Localsetup's optional context retrieval layer. It keeps files as the source of truth, then builds a disposable SQLite search/cache database so agents can ask deterministic questions before falling back to direct file reads.

## What It Provides

- Vector-first local RAG using SQLite tables, SQLite FTS5, and deterministic local hash embeddings by default.
- Repo and framework context segregation through `tenant_slug`, `namespace_slug`, `corpus_slug`, `scope_slug`, and `context_key`.
- UUIDv7 IDs for relational rows so separately created SQLite databases can be merged later without ID collisions.
- Freshness, worklist, and agent-preflight JSON surfaces that tell agents which paths are stale, missing, deleted, or safe to search.
- Reset and rebuild controls for disposable index recovery.
- JSONL operation logs with rotation and pragmatic secret/noise filtering.

## Default Storage

- Repo scope: `.localsetup/context-index/context-index.sqlite3`
- Framework scope: global DB, `~/.local/share/localsetup/context-index/context-index.sqlite3`

The repo DB is ignored by the default inventory rules and is not intended to be committed. The global DB carries framework index data only.

## Core Commands

```bash
localsetup context-index doctor
localsetup context-index agent-preflight --scope repo
localsetup context-index freshness --scope repo
localsetup context-index worklist --scope repo
localsetup context-index stats --scope repo
localsetup context-index ingest --scope repo
localsetup context-index search "workflow registry" --scope repo --top-k 10
localsetup context-index lookup --chunk-id UUID
localsetup context-index vector-rebuild plan --scope repo
localsetup context-index vector-rebuild apply --scope repo --plan PLAN_ID
localsetup context-index rebuild plan --scope repo
localsetup context-index rebuild apply --scope repo --plan PLAN_ID
localsetup context-index prune plan --scope repo
localsetup context-index prune apply --scope repo --plan PLAN_ID
localsetup context-index worker nudge --scope repo
localsetup context-index logs status --scope repo
localsetup context-index mcp config --scope repo
```

All agent-facing commands emit JSON. Agents should check `freshness`, `worklist`, or `agent-preflight` first, then use search only for paths that are not listed in `read_direct_paths`.

## Indexed Data

By default the repo scope indexes text-like files, docs, skills, workflows, generated context catalogs, code files, configuration files, and image metadata stubs. Obvious build/runtime/cache/noise paths are excluded, as are `.env`, vault, key, token, credential, log, and common secret-looking files.

Image files are represented as metadata-only text in this first implementation. The schema has `modality` and vector profile fields so richer CLIP or multimodal embeddings can be added without changing the agent command contract.

## Database Indexing

The SQLite schema is deliberately relational and future PostgreSQL-friendly. Common agent paths have native indexes:

- `sources(context_key, repo_relative_path)` for direct lookup.
- `sources(context_key, freshness_status, priority, repo_relative_path)` for freshness/worklists.
- `sources(tenant_slug, namespace_slug, corpus_slug, scope_slug, repo_relative_path)` for future merged/central databases.
- `chunks(context_key, repo_relative_path, line_start, line_end)` for provenance lookup.
- `vectors(context_key, embedding_profile_id)` and `vectors(embedding_profile_id, context_key, modality)` for vector scans by profile/scope.
- FTS5 virtual table `chunk_fts` for lexical fallback.

`stats` reports table counts, DB size, FTS availability, and index names. `prune` is conservative: it removes tombstoned/deleted source rows and orphan vector rows from the selected context, never source files.

## Configuration

Run `config init` to create a config file, then tune storage, includes/excludes, chunking, embedding provider names, model names, dimensions, retrieval weights, worker limits, and logging. The default provider is `local_hash`; `openai_compatible`, `openai`, and `llama_cpp` route to a configured OpenAI-compatible HTTP embeddings endpoint, which can be a hosted API or local server. See [schemas/config.schema.json](schemas/config.schema.json).

## Safety Contract

The index is never canonical. If `freshness` marks a path as stale, changed, deleted, or not indexed, the agent must read that file directly before relying on search results. The reset/rebuild commands are safe because the database is derived state and can be regenerated from source files.

## MCP Status

`mcp config` emits a deterministic optional MCP server configuration. MCP serving is intentionally not a hard dependency; `ls/tools/context_mcp_server.py` is present as the stable wrapper target and reports a structured optional-dependency error until an MCP SDK implementation is enabled.

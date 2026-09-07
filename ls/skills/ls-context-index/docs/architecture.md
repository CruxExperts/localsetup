# Architecture

`ls-context-index` is a thin LocalSetup RAG layer over source files. It speeds up retrieval but does not replace Markdown, code, manifests, or generated catalogs as source of truth.

## Component Model

```text
inventory -> freshness -> chunking -> embedding -> SQLite upsert
                              |
                              v
              search/lookup/worklist/agent-preflight
```

The implementation lives in `ls/tools/context_index.py`. The top-level command wrapper is:

```bash
localsetup context-index ...
```

## Storage

- Repo DB: `.localsetup/context-index/context-index.sqlite3`
- Global DB: `~/.local/share/localsetup/context-index/context-index.sqlite3`
- Repo logs: `.localsetup/context-index/logs/context-index.jsonl`
- Global logs: `~/.local/share/localsetup/context-index/logs/context-index.jsonl`

Framework and global/user context share the global DB. Repo context uses a repo DB by default unless config changes `storage.mode` to `global` or `central_sqlite`.

## Scope And Identity

Each context uses:

```text
tenant_slug / namespace_slug / corpus_slug / scope_slug
```

The combined `context_key` is present on sources, chunks, vectors, runs, freshness snapshots, workers, and reset plans. This lets one DB contain several repos or a merged global corpus without losing isolation.

## Schema Highlights

- `contexts`: scope identity records.
- `sources`: one row per file/path in a context, with size, mtime, content hash, config hashes, priority, source type, modality, and freshness status.
- `chunks`: line-range provenance and chunk text.
- `chunk_fts`: SQLite FTS5 lexical fallback.
- `embedding_profiles`: provider/model/dimension identity.
- `vectors`: packed float vector blobs by chunk/profile/modality.
- `freshness_snapshots`, `ingest_runs`, `reset_plans`, `worker_runs`, `worker_locks`: deterministic operation records.

All primary relational IDs are UUIDv7 strings.

## Native Indexes

The schema adds SQL-native indexes for common searches instead of requiring agents to scan tables:

- `sources(context_key, repo_relative_path)`
- `sources(context_key, freshness_status, priority, repo_relative_path)`
- `sources(context_key, priority, freshness_status, repo_relative_path)`
- `sources(tenant_slug, namespace_slug, corpus_slug, scope_slug, repo_relative_path)`
- `chunks(source_id, line_start, line_end)`
- `chunks(context_key, repo_relative_path, line_start, line_end)`
- `vectors(context_key, embedding_profile_id)`
- `vectors(embedding_profile_id, context_key, modality)`
- `worker_runs(context_key, status, started_at)`

These indexes support freshness, worklists, lookup, scope merge, vector profile filtering, and worker status checks.

## Freshness

Freshness compares inventory results with indexed source metadata:

- Missing DB record -> `not_indexed`
- Size/mtime/hash/config mismatch -> `changed` or `needs_reembed`
- DB record with no source file -> `deleted`
- No discrepancy -> `fresh`

`stale-files` emits `read_direct_paths` so agents can avoid trusting old index content.

## Retrieval

Search combines:

- SQLite FTS5 lexical scores.
- Local deterministic vector scores from packed vector blobs.
- Hybrid ranking weights from config.

The default embedding provider is `local_hash`, which is deterministic, local, no-network, and testable. Config keeps provider/model/dimensions explicit. `openai_compatible`, `openai`, and `llama_cpp` are names for the same HTTP adapter, not independent implementations. Verified targets are OpenAI's `/v1/embeddings` endpoint and llama.cpp's compatible endpoint when it serves an embedding-capable model with non-`none` pooling. Other services need provider-specific compatibility checks.

`vector-rebuild plan|apply` recomputes vector rows for existing chunks without re-extracting source files. This is the intended path after embedding provider, model, prefix, or dimension changes when source chunks are otherwise acceptable.

## Pruning

`prune plan|apply` removes only derived database rows for sources already tombstoned as deleted and any orphan vector rows. It never removes files from disk and remains single-scope by design.

## Worker And Heartbeat

`worker nudge` is designed for heartbeat integration. It checks the worklist and queues a worker run record when work exists. Actual indexing can run through `worker run` or another configured worker so the heartbeat does not block on long indexing jobs.

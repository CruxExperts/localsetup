# Platform Evaluation

Snapshot date: 2026-05-12.

## Decision

Use SQLite as the default Localsetup context-index backend, with FTS5 for lexical search and ordinary relational tables for vector payloads, freshness metadata, source provenance, and memory usage. Keep the schema generic enough to migrate to PostgreSQL later.

This follows the user's portability requirement: each enabled repo can have its own copyable SQLite DB, while framework and global context share one global SQLite DB. Context columns (`tenant_slug`, `namespace_slug`, `corpus_slug`, `scope_slug`, `context_key`) let one database contain many repos or let several repo DBs be merged into a central database later.

## Candidate Summary

| Candidate | Fit | Decision |
|---|---|---|
| SQLite FTS5 + relational vector blobs | Excellent portability, no service, native full-text, easy backup, CI-friendly | Selected default |
| PostgreSQL + pgvector/FTS | Strong future central store, multi-repo consolidation, concurrency | Future backend target, not default |
| LanceDB | Good embedded vector store and hybrid features, but adds a larger dependency and another storage format | Consider later adapter |
| Qdrant | Strong production vector DB and filtering, Docker/service friendly | Advanced backend only |
| Qdrant MCP server | Useful integration pattern, but does not own Localsetup provenance/freshness/security semantics | Reference only |
| Chroma | Easy local vector use, but less aligned with SQL-native freshness/worklist requirements | Not selected |
| Meilisearch | Strong lexical/hybrid service, but service footprint is too heavy for default Localsetup | Not selected |
| Tantivy/BM25S | Useful lexical fallback, but does not cover relational freshness and merge requirements alone | Not selected |
| Milvus Lite / Weaviate | Powerful but heavier than needed for repo-local default | Not selected |
| FAISS | Fast vector library, but no native metadata/freshness/control-plane DB | Not selected |
| LangChain / LangGraph | Useful RAG/memory architecture references, but Localsetup needs deterministic framework-native tooling | Reference only |

## Why SQLite

SQLite is already compatible with Localsetup's local-first and Python-first stance. It gives deterministic file-level state, WAL support, ordinary indexes, `sqlite_master`-visible schema validation, FTS5 lexical search, and low-friction test execution without network or Docker. The implementation stores vectors as packed float blobs and scans by `context_key` + embedding profile; this is acceptable for repo-scale indexes and keeps the schema easy to migrate to PostgreSQL. Embeddings default to deterministic local hash vectors for offline use, with an explicit OpenAI-compatible HTTP adapter for hosted APIs or local llama.cpp-style servers.

## Native Index Strategy

The schema includes explicit indexes for common agent and worker paths:

- Source lookup: `idx_sources_context_path`
- Freshness/worklist: `idx_sources_context_freshness`, `idx_sources_context_priority_status`
- Merge/consolidation: `idx_sources_scope_lookup`, `idx_sources_context_fingerprint`
- Provenance lookup: `idx_chunks_source_line`, `idx_chunks_context_line_lookup`
- Vector search profile filtering: `idx_vectors_context_profile`, `idx_vectors_profile_modality`
- Memory curation: `idx_usage_chunk`, `idx_usage_context_used`
- Worker visibility: `idx_worker_runs_context_status`
- Lexical fallback: `chunk_fts` FTS5 virtual table

These indexes are deliberately SQL-native so agents and tests can validate them with ordinary SQLite introspection.

## LangChain And LangGraph Notes

LangChain and LangGraph show useful RAG and memory patterns: retrieval pipelines, document provenance, stateful memory, and graph-style maintenance flows. Localsetup borrows the architectural lessons but not the runtime dependency. The Localsetup command surface must remain deterministic, local-first, and aligned with framework files, so it implements its own CLI and schema.

## Sources Checked

- LangChain RAG docs: https://docs.langchain.com/oss/python/langchain/rag
- LangChain memory concepts: https://docs.langchain.com/oss/python/concepts/memory
- LangGraph repository: https://github.com/langchain-ai/langgraph
- LangGraph product/docs overview: https://www.langchain.com/langgraph
- SQLite FTS5: https://www.sqlite.org/fts5.html
- UUIDv7 / RFC 9562: https://www.rfc-editor.org/rfc/rfc9562
- PostgreSQL UUID docs: https://www.postgresql.org/docs/current/datatype-uuid.html

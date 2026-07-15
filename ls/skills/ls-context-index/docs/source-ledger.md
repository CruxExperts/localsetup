# Source Ledger

Snapshot date: 2026-05-12.

## Localsetup Sources

- `ls/tools/context_index.py`: runtime implementation source of truth.
- `ls/core/cli.py`: top-level `localsetup.py context-index` delegation.
- `ls/config/pack.yaml`: skill/workflow pack registration.
- `ls/workflows/ls-workflow-context-index-query/workflow.yaml`: query workflow package.
- `ls/workflows/ls-workflow-context-index-refresh/workflow.yaml`: refresh workflow package.
- `ls/docs/SKILLS.md` and `ls/docs/WORKFLOW_REGISTRY.md`: generated catalogs updated from source manifests.

## Upstream And Comparative Sources

- SQLite FTS5 official docs: https://www.sqlite.org/fts5.html
- RFC 9562 UUIDv7: https://www.rfc-editor.org/rfc/rfc9562
- PostgreSQL UUID type docs: https://www.postgresql.org/docs/current/datatype-uuid.html
- LangChain RAG docs: https://docs.langchain.com/oss/python/langchain/rag
- LangChain repository: https://github.com/langchain-ai/langchain
- LangGraph repository: https://github.com/langchain-ai/langgraph
- LangGraph overview: https://www.langchain.com/langgraph

## Verification Evidence To Keep Current

- `uv run --locked python -m json.tool ls/skills/ls-context-index/schemas/config.schema.json`
- `uv run --locked python -m py_compile ls/tools/context_index.py`
- `uv run --locked pytest ls/tests/test_context_index.py -q`
- `uv run --locked python ls/tools/localsetup.py --source-root . validate-catalog`
- `uv run --locked python ls/tools/context_index.py --repo . stats --json`
- `uv run --locked python ls/tools/context_index.py --repo . vector-rebuild plan --json`
- `uv run --locked python ls/tools/context_index.py --repo . prune plan --json`

## Boundaries

This skill documents and operates Localsetup's own implementation. LangChain and LangGraph are design references, not runtime dependencies. The index is derived state; source files remain authoritative.

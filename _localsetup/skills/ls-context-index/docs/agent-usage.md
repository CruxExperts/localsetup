# Agent Usage

Use `context-index` before broad recursive reads when the capability is enabled. Verify stale or high-impact results against the files before changing code or making exact claims.

## Preflight

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index agent-preflight --scope repo
```

Important fields:

- `vector_available`: whether vectors exist for the scope.
- `freshness.safe_to_use_index`: whether the indexed files are current.
- `freshness.agent_guidance.read_direct_paths`: files to read directly.
- `worklist`: pending extract/chunk/embed/tombstone counts.

## Search

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index search "how are workflows registered" --scope repo --top-k 10
python3 _localsetup/tools/localsetup_v3.py --repo . context-index search "memory promotion rules" --scope global --top-k 10
python3 _localsetup/tools/localsetup_v3.py --repo . context-index search "skill validation smoke commands" --scope framework --mode hybrid --top-k 10
```

Result rows include rank, score, vector score, lexical score, scope, path, line range, snippet, chunk ID, source hash, chunk hash, and stale status.

## Lookup

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index lookup --chunk-id UUID
```

Use lookup when a search result is important enough to inspect in full. For code edits, still open the source file by path and line range.

## Freshness And Worklists

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index freshness --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index stale-files --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index worklist --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index stats --scope repo
```

If a file is listed in `read_direct_paths`, read it directly before using index results for that file.

## Ingest And Refresh

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index ingest --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index refresh --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index worker nudge --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index worker run --scope repo
```

`refresh` and `worker run` use changed-only ingest. `worker nudge` is safe for heartbeat because it only queues work when a deterministic worklist exists.

## Reset And Rebuild

```bash
PLAN=$(python3 _localsetup/tools/localsetup_v3.py --repo . context-index rebuild plan --scope repo)
python3 _localsetup/tools/localsetup_v3.py --repo . context-index rebuild apply --scope repo --plan PLAN_ID
```

Use rebuild when the index is contaminated, when embedding settings changed, or when maintainers request a clean reindex. The database is disposable derived state.

For vector-only refreshes:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index vector-rebuild plan --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index vector-rebuild apply --scope repo --plan PLAN_ID
```

For conservative cleanup of deleted/tombstoned indexed sources:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index prune plan --scope repo
python3 _localsetup/tools/localsetup_v3.py --repo . context-index prune apply --scope repo --plan PLAN_ID
```

## Agent Rules

- Prefer `repo` for repo work, `framework` for Localsetup framework questions, and `global` only when user/global memory is relevant.
- Never ask the index for secret values.
- Mark stale results as context hints only.
- Prefer `ACTIVE` docs where status is available.
- Use direct file reads for exact edits and citations.

## MCP Config

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index mcp config --scope repo
```

This emits a read-only stdio server command target for MCP-capable clients. Live serving is optional and requires enabling the MCP SDK wrapper; the deterministic CLI remains the supported baseline.

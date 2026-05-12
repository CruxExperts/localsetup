# Memory Curation

Memory curation tracks which retrieved chunks actually influenced agent work. It does not silently promote private repo content into global memory.

## Usage Tracking

After a result materially helps, agents may mark it used:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index memory mark-used --scope repo --chunk-id UUID --reason selected_context
```

This inserts a UUIDv7 `usage_events` row with `chunk_id`, `context_key`, `reason`, and `used_at`. The row is indexed by chunk and by `context_key, used_at` so usage reports and promotion scans stay cheap.

## Stats

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index memory stats --scope repo
```

Stats group usage by chunk and include path and last-used timestamp.

## Promotion Planning

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context-index memory promote-plan --scope repo
```

The plan reports candidates that meet `context_index.memory.min_uses_for_promotion`. Apply is intentionally conservative in this implementation: it does not mutate global memory files until a repo-approved memory writer and privacy policy are configured.

## Protection Rules

Agents should not prune or promote:

- Stale chunks.
- Secret-like or private user material.
- Repo-specific implementation notes that would confuse unrelated repos.
- Anything not verified against the source file.

## Privacy

The index stores usage reasons as bounded strings. Do not include raw private query text or secrets in `--reason`.

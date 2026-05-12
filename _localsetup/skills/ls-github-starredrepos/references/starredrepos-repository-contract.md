# Starredrepos Repository Contract

Default repository name: `starredrepos`.
Default local worktree when `STARREDREPOS_WORKTREE` is unset: `~/starredrepos`.

Recommended layout:

```text
README.md
manifest.json
snapshots/
  latest.json
  diffs/
docs/
  repos/
scouts/
  reports/
modules/
```

## Rules

- `manifest.json` follows `data/schema/manifest.schema.json`.
- `snapshots/latest.json` is the latest complete inventory.
- `snapshots/diffs/` stores diff reports between runs.
- `docs/repos/` stores generated per-repository notes.
- `modules/` stores submodule pointers only after guarded submodule creation is implemented and explicitly selected.
- Local checkout caches and bare mirrors are never committed.

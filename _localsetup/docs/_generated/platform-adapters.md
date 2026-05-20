---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: d4740350957e3efec61ffb7457d5521d279a7f2dbfdebc01873bc6cd12ea9f20
  emitter: generate-docs
framework_version: 4.0.1
source_commit: e2c5d0c87631e0230884e8ae08fe0af41a93fcc8
artifact_sha256: 4630cfc4d0d8f3305c3e4eb47fd9f3b85e232d651993e5635e70e7dd3dd3a8f1
---
# Platform Adapters

Repo adapter paths are attached only when selected with `--tools` or `--platforms`; a selector-free install is global-only.

| Platform | Repo Paths | Verify Rules |
|---|---|---|
| `codex` | `.codex/skills` | `skills_visible, namespace_ls` |
| `claude-code` | `.claude/skills` | `skills_visible, namespace_ls` |
| `cursor` | `.cursor/skills` | `skills_visible, namespace_ls` |
| `kilo` | `.kilo/skills` | `skills_visible, namespace_ls` |
| `opencode` | `.opencode/skills` | `skills_visible, namespace_ls` |
| `openclaw` | `.openclaw/skills` | `skills_visible, namespace_ls` |

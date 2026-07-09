---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: ff1a1dcfb75019d9a213a6e7b9ead19509f451070a014fe54b0059cfa1c9adc2
  emitter: generate-docs
framework_version: 4.2.14
source_commit: aa89c3cb46d6e96183cf342c83e5f82fb9751d7d
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

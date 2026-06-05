---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 69ca368c6d2ca1af3288ef0f8814ffd866c8ee05a000ac1edeea38b15e269633
  emitter: generate-docs
framework_version: 4.0.20
source_commit: 3ed663064efd13c061fb20d36c5b86e17bac8ad4
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

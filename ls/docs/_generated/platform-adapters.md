---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 7bc8aca3feeaecc98a7e06a37c96fea10a9bd571aa7f217094148632d1bd94c6
  emitter: generate-docs
framework_version: 4.3.8
source_commit: 1e6b18d05fb95f0ae53ed62469f2ac3e16afc95e
artifact_sha256: 55b4564bc1cfe9ab17621d0028dd97743d9f2350f84606aa59d20dc7aede63e1
---
# Platform Adapters

Repo adapter paths are attached only when selected with `--tools` or `--platforms`; a selector-free install is global-only.

| Platform | Repo Paths | Verify Rules |
|---|---|---|
| `codex` | `.agents/skills` | `skills_visible, namespace_ls` |
| `claude-code` | `.claude/skills` | `skills_visible, namespace_ls` |
| `cursor` | `.agents/skills, .cursor/skills` | `skills_visible, namespace_ls` |
| `kilo` | `.kilo/skills` | `skills_visible, namespace_ls` |
| `opencode` | `.opencode/skills` | `skills_visible, namespace_ls` |
| `openclaw` | `.agents/skills` | `skills_visible, namespace_ls` |

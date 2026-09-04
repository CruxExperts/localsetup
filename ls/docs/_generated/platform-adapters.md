---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: f1c0c3b66c0b244eb3413d5e244c72ce2829d0b74b23432bc8bb48d335c65430
  emitter: generate-docs
framework_version: 4.3.9
source_commit: 9d0e794128e0b02b4829ea21842b9912e61b3369
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

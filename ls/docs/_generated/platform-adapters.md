---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 8463b48224dd9bbd4432dfddf8cd8692fa9a6faf4382a5d8978f2e67401c2abe
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 8ca28c8dcf656684dda0145ddcb9904efd68b851
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

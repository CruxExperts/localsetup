---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 656b9c07546f2fad7ff4ea1c55dbbc837887c61cdd933b9954e8ffd7ebf9601e
  emitter: generate-docs
framework_version: 4.3.9
source_commit: 246cadba334cae02cb847b0d5db4666c82159030
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

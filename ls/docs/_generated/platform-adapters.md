---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 6192e56d53f7ad47346a46cd550ccc6695903dd826258257319ee7e2d45c7ddb
  emitter: generate-docs
framework_version: 4.3.9
source_commit: 85a76e6d2fc60370a7b405e6ef3a8b634b0259e6
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

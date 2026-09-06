---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: c6370a360b2767441c3a73ce8900a9db56d3f05a421c89a3eb7f9941d56cc73e
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 01a2d1895f37feae759958524c70065f22c9f958
artifact_sha256: 2b5524b4bdba59d5d6e568fc293ff85ae0485f32943f75efc11ae08039b8736f
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
| `github-copilot-cli` | `.agents/skills` | `skills_visible, namespace_ls` |
| `github-copilot-vscode` | `.agents/skills` | `skills_visible, namespace_ls` |

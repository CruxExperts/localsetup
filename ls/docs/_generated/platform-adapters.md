---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: c38f3605e85fb0c27a68608233747759f96961a62ac936d6ec466d848e6877c6
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 4dd5461e1afd4ff881c1d03a26f967d804c7ba4e
artifact_sha256: 870d70ce5ac847df19f130265c2c4ea5982215c51387e158dc7f5fdf3086357e
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
| `cline-cli` | `.cline/skills` | `skills_visible, namespace_ls` |
| `cline-vscode` | `.cline/skills` | `skills_visible, namespace_ls` |
| `amp-cli` | `.agents/skills` | `skills_visible, namespace_ls` |
| `goose-cli` | `.agents/skills` | `skills_visible, namespace_ls, goose_skills_configured` |
| `pi-cli` | `.agents/skills` | `skills_visible, namespace_ls` |

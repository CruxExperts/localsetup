---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 27df6c31e07f5f6160e18098e76320c18f4d9d5c705b37ddac6d948aa60a3d50
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 053744f927efcf793ee1fcdb7b5d3be5b359eb65
artifact_sha256: 6c4386404f9dce64c3ef62a86a37f46434731dd767d8abd6426cc2b0564ab3f2
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

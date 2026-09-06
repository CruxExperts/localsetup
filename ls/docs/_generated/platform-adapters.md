---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: f0efcb31df4fdd276796dfb2512ad81cd7f4737264edabb4b00829c90f2c8171
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 1c8e7476e990c51470298fd853ab266f4ef13bb0
artifact_sha256: 4fa77910721e341f34098d8e9e13f626a1b9556765b8b39a35d9b4324b328228
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
| `hermes-agent` | `.hermes/skills` | `skills_visible, namespace_ls` |
| `qwen-code-cli` | `.agents/skills` | `skills_visible, namespace_ls` |

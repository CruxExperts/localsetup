---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: 730dcafaadfcf238d54d9521ee0316e5c2326591e3626adf93aa975f1f3de092
  emitter: generate-docs
framework_version: 4.4.1
source_commit: 0dae5c430aae571029e5e8992af6fa909b2ad314
artifact_sha256: 62eb3c81d7eb506ccece5a2f1afacdafc424bbcf71fea316bc7ec4b221c54a8b
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

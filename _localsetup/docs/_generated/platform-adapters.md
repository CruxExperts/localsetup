---
localsetup_provenance:
  schema_version: 1
  source_provenance_hash: edf375ba73b6eaa21caeaec1546c0945f78987a894b9a74266b943b00f16fecc
  emitter: generate-docs
framework_version: 4.0.20
source_commit: 88c59b6ea11064a8c937b394b4ddc4d96cf11a18
artifact_sha256: 4630cfc4d0d8f3305c3e4eb47fd9f3b85e232d651993e5635e70e7dd3dd3a8f1
---
# Platform Adapters

Repo adapter paths are attached only when selected with `--tools` or `--platforms`; a selector-free install is global-only.

| Platform | Repo Paths | Verify Rules |
|---|---|---|
| `codex` | `.codex/skills` | `skills_visible, namespace_ls` |
| `claude-code` | `.claude/skills` | `skills_visible, namespace_ls` |
| `cursor` | `.cursor/skills` | `skills_visible, namespace_ls` |
| `kilo` | `.kilo/skills` | `skills_visible, namespace_ls` |
| `opencode` | `.opencode/skills` | `skills_visible, namespace_ls` |
| `openclaw` | `.openclaw/skills` | `skills_visible, namespace_ls` |

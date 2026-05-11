---
status: ACTIVE
version: 3.1
---

# Repo and data separation (Localsetup v3)

**Purpose:** The framework lives in the client repo at `_localsetup/`. Only modify local context (e.g. `.cursor/rules/local-*.mdc`) or propose changes via PRD; do not edit framework engine files in place for one-off overrides.

## Separation

- **Engine**  - Contents of `_localsetup/` (framework code, docs, skills, workflow packages, templates). Upgrades replace this folder; do not rely on local edits inside it for permanent overrides.
- **Local context**  - Repo-root files such as `.cursor/rules/local-*.mdc` or platform-specific overrides. Safe to edit for project-specific rules.
- **Proposals**  - For framework behavior changes, use the Agent Q / PRD flow; see [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).

## Source and runtime boundaries

- `_localsetup/skills/` and `_localsetup/workflows/` are framework source.
- `~/.local/share/agents/skills/localsetup` is managed runtime output and can be recreated by install.
- Platform adapter paths such as `.codex/skills`, `.kilo/skills`, and `.cursor/skills` are attachments to the managed runtime library, not new source roots.
- Generated workflow docs come from `_localsetup/workflows/*/workflow.yaml`; do not treat generated registry rows as source edits.

## Reference

- [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md)  - Attach git hash when referencing PRDs, specs, outcomes.
- [AGENTIC_DESIGN_INDEX.md](AGENTIC_DESIGN_INDEX.md)  - Index of framework docs.
- [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md)  - Source/runtime model for first-class workflow packages.

---
status: ACTIVE
version: 3.7
---

# Repo and data separation (Localsetup v3)

**Purpose:** The framework lives in the client repo at `_localsetup/`. Only modify local context (e.g. `.cursor/rules/local-*.mdc`) or propose changes via PRD; do not edit framework engine files in place for one-off overrides.

## Separation

- **Engine**  - Contents of `_localsetup/` (framework code, docs, skills, workflow packages, templates). Upgrades replace this folder; do not rely on local edits inside it for permanent overrides.
- **Local context**  - Repo-root files such as `.cursor/rules/local-*.mdc` or platform-specific overrides. Safe to edit for project-specific rules.
- **Mutable state**  - Project/user state such as memory, reminders, backlog, temporary notes, harness state, and runtime logs belongs in approved repo-level or platform-owned paths outside `_localsetup/`.
- **Proposals**  - For framework behavior changes, use the Agent Q / PRD flow; see [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).

## Source and runtime boundaries

- `_localsetup/skills/` and `_localsetup/workflows/` are framework source.
- Never store reminders, backlog, agent memory, temporary notes, or other mutable project/user state under `_localsetup/`. If that happens accidentally, move it to an approved mutable-state path and revert the framework-source change.
- `~/.local/share/agents/skills/localsetup` is managed runtime output and can be recreated by install.
- Explicitly selected platform adapter paths such as `.codex/skills`, `.kilo/skills`, and `.cursor/skills` are attachments to the managed runtime library, not new source roots. A global-only install creates no repo adapter paths.
- Harness activation files such as `HEARTBEAT.md`, `config/codex_heartbeat.yaml`, `cron/manifest.yaml`, and `state/codex-heartbeat/` are target-repo state created only by explicit harness commands, not by normal install.
- Generated workflow docs come from `_localsetup/workflows/*/workflow.yaml`; do not treat generated registry rows as source edits.

## Reference

- [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md)  - Attach git hash when referencing PRDs, specs, outcomes.
- [AGENTIC_DESIGN_INDEX.md](AGENTIC_DESIGN_INDEX.md)  - Index of framework docs.
- [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md)  - Source/runtime model for first-class workflow packages.
- [HARNESS_AUTOMATION.md](HARNESS_AUTOMATION.md)  - Opt-in harness activation and runtime artifact boundaries.

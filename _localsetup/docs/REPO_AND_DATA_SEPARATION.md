---
status: ACTIVE
version: 4.0
owner_skill: ls-framework-compliance
---

# Repo and data separation (Localsetup v3)

**Purpose:** Localsetup framework source lives in the registered source checkout, normally `~/.local/share/localsetup/source` or a contributor checkout. Consuming repos keep target-owned state under `.localsetup/` and selected adapter paths only.

## Separation

- **Source checkout**  - Contents of `_localsetup/` in the Localsetup source tree: framework code, docs, skills, workflow packages, templates, and tests.
- **Target state**  - `.localsetup/lock.json`, `.localsetup/install-journal/`, `.localsetup/backups/`, `.localsetup/context-index/`, and `.localsetup/state/` in consuming repos.
- **Local context**  - Repo-root files such as `.cursor/rules/local-*.mdc` or platform-specific overrides. Safe to edit for project-specific rules.
- **Mutable state**  - Project/user state such as memory, reminders, backlog, temporary notes, harness state, and runtime logs belongs in approved repo-level or platform-owned paths outside `_localsetup/`.
- **Proposals**  - For framework behavior changes, use the Agent Q / PRD flow; see [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).

## Source and runtime boundaries

- `_localsetup/skills/` and `_localsetup/workflows/` are framework source in the Localsetup source checkout.
- A consuming repo should not contain `_localsetup/` by default. Treat a target `_localsetup/` as stale legacy framework source unless the target is the Localsetup source checkout itself.
- Never store reminders, backlog, agent memory, temporary notes, or other mutable project/user state under `_localsetup/`. If that happens accidentally, move it to an approved mutable-state path and revert the framework-source change.
- `~/.local/share/localsetup/packages` is managed runtime output and can be recreated by install.
- Explicitly selected platform adapter paths such as `.codex/skills`, `.kilo/skills`, and `.cursor/skills` are attachments to the managed runtime library, not new source roots. A global-only install creates no repo adapter paths.
- Harness activation files such as `HEARTBEAT.md`, `config/codex_heartbeat.yaml`, `cron/manifest.yaml`, and `.localsetup/state/codex-heartbeat/` are target-repo state created only by explicit harness commands, not by normal install.
- Generated workflow docs come from `_localsetup/workflows/*/workflow.yaml`; do not treat generated registry rows as source edits.

## Reference

- [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md)  - Attach git hash when referencing PRDs, specs, outcomes.
- [AGENTIC_DESIGN_INDEX.md](AGENTIC_DESIGN_INDEX.md)  - Index of framework docs.
- [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md)  - Source/runtime model for first-class workflow packages.
- [HARNESS_AUTOMATION.md](HARNESS_AUTOMATION.md)  - Opt-in harness activation and runtime artifact boundaries.

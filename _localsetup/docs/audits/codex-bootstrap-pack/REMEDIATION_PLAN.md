---
status: ACTIVE
version: 3.7
date: 2026-05-10
---

# Codex Bootstrap-Pack Remediation Plan

## Principles

- Keep Codex native: config TOML, AGENTS.md, custom agent TOMLs, native subagents, plan/goal mode, markdown runbooks, and small YAML metadata.
- Keep repo-local bootstrap-pack work separate from approval-gated global changes.
- Prefer deterministic dry-runs, hashes, and generated indexes over ad hoc folder replacement.
- Preserve user-owned global and external-folder state until explicitly approved.

## Phase 1: Repo-Local Bootstrap Pack

Status: implemented in this audit.

Evidence:

- `_localsetup/config/pack.yaml` includes `bootstrap`.
- `_localsetup/docs/bootstrap-packs/INDEX.md` exists.
- `_localsetup/docs/bootstrap-packs/codex-agent-team/metadata.yaml` exists.
- `_localsetup/docs/bootstrap-packs/codex-agent-team/AUDIT_PROMPT.md` exists.
- Generated pack/file indexes include bootstrap-pack entries.

## Phase 2: Global Codex Hardening

Status: approval required.

Tasks:

- Add explicit override language to `<codex-home>/AGENTS.md`.
- Decide whether `agents.max_threads = 6` is headroom or policy, then update docs or config.
- Align `<codex-home>/AGENT_TEAM_RUNBOOK.md` wording with `xhigh` reasoning.
- Tighten global Codex file permissions if no shared-group workflow requires current group-write modes.

Validation:

- Parse TOML with `tomllib`.
- Run `codex debug prompt-input` from a non-repo directory.
- Run `codex debug prompt-input` from this repo and confirm repo-local instructions still load.

## Phase 3: Legacy Skill/Prompt Replacement Dry Run

Status: plan only; approval required before external writes.

Tasks:

- Build a canonical manifest from `_localsetup/skills`, `_localsetup/templates`, and `_localsetup/config`.
- Generate `localsetup-*` to `ls-*` alias mapping from the current repo.
- Compare candidate legacy trees by hash:
  - `<legacy-localsetup-repo>/.agents/skills`
  - `~/.codex/skills`
  - runtime mirror under `~/.local/share/agents/skills/localsetup`
- Emit a dry-run report with no file mutations.

Validation:

- Parse generated manifest.
- Confirm all compared paths are classified as canonical, runtime mirror, legacy duplicate, or placeholder.
- Require user approval before any replacement or permission change.

## Phase 4: Future Framework Adapters

Status: deferred.

Tasks:

- Add metadata entries for OpenCode, Kilo, Cursor, Claude Code, or OpenClaw only after source-backed behavior is verified.
- Keep platform-specific prompts under the bootstrap-pack docs tree.
- Do not claim parity with Codex until each platform has its own audit prompt and validation checklist.

## Stop Conditions

Stop and request approval before:

- Writing outside `<repo-root>`.
- Changing `<codex-home>` or any `$CODEX_HOME` path.
- Replacing or deleting legacy skills/prompts/configs.
- Changing permissions outside the current repo.
- Performing network-mutating or global install operations.

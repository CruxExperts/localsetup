---
status: ACTIVE
version: 3.2
---

# Platform registry (Localsetup v3)

**Purpose:** Single source of truth for which AI agent platforms the framework supports. When you need to list supported platforms, reference this file instead of scattering names across docs. When adding a new platform, add it here first; when registering a new skill or workflow package, use the registration lists below so no platform is missed.

**Manifest source:** V3 installer behavior is controlled by `_localsetup/config/platforms.yaml`. This page is a human-readable summary. The root `--tools` flag remains a compatibility alias for v3 `--platforms`.

## Supported platforms

| ID | Display name | Repo adapter path | Managed package library |
|----|--------------|-------------------|-----------------------|
| cursor | Cursor | .cursor/skills | ~/.local/share/agents/skills/localsetup |
| claude-code | Claude Code | .claude/skills | ~/.local/share/agents/skills/localsetup |
| codex | OpenAI Codex CLI | .codex/skills | ~/.local/share/agents/skills/localsetup |
| openclaw | OpenClaw | .openclaw/skills | ~/.local/share/agents/skills/localsetup |
| kilo | Kilo CLI | .kilo/skills | ~/.local/share/agents/skills/localsetup |
| opencode | OpenCode CLI | .opencode/skills | ~/.local/share/agents/skills/localsetup |

*More platforms may be added later. Update this table and the "Skill registration (new skills)" section when adding one.*

## Shared home library

V3 installs selected skills and workflow packages to `~/.local/share/agents/skills/localsetup`. Repo adapter paths attach to that library only when selected with `--tools` or `--platforms`; omitted selectors are global-only and create no adapters. `--mode portable` creates managed copies instead of symlinks. Rollback uses `localsetup.lock.json` and removes only managed paths recorded by that install.

## Skill registration (new skills)

When adding a new framework skill, register it in **every** file below so the skill appears in each platform's context and in the framework README. Paths are relative to the **framework source root** (the directory that contains `templates/`, `skills/`, `workflows/`, and `docs/`).

Add one row or bullet per new skill with a short "When to use" description. Use the same phrasing everywhere.

| Platform / scope | File to update |
|-----------------|----------------|
| Cursor (templates) | _localsetup/templates/cursor/ls-context-index.md |
| Cursor (templates) | _localsetup/templates/cursor/ls-context.mdc |
| Claude Code | _localsetup/templates/claude-code/CLAUDE.md |
| Codex | _localsetup/templates/codex/AGENTS.md |
| OpenClaw | _localsetup/templates/openclaw/OPENCLAW_CONTEXT.md |
| OpenCode | _localsetup/templates/opencode/AGENTS.md |
| Kilo (templates) | _localsetup/templates/kilo/instructions.md |
| Framework docs index | _localsetup/docs/README.md |
| Context skill (source) | _localsetup/skills/ls-context/SKILL.md |

**If you add a new platform:** extend the Supported platforms table above, add the platform's context/skills paths, and add the corresponding registration file(s) to this table so the skill-creator and maintainers keep all platforms in sync.

## Workflow registration (new workflow packages)

When adding a new workflow package, create `_localsetup/workflows/ls-workflow-<id>/SKILL.md` and `workflow.yaml`, then update the same platform context templates when the workflow should be visible as a common trigger. Generated workflow catalogs are refreshed from `workflow.yaml`.

Use [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md) for the model and [WORKFLOW_STANDARD.md](WORKFLOW_STANDARD.md) for the manifest contract.

## Reference

- V3 CLI: `_localsetup/tools/localsetup_v3.py plan|install|verify|rollback`.
- Root wrapper: `./install --directory . --yes` for global-only; use `--tools cursor,codex` or `--platforms cursor codex` to select adapters. Use `--target-directory /path/to/project` to attach selected adapters outside the source checkout.
- Windows: WSL2-only. `install.ps1` is a guidance stub, not a native installer.
- Skills and rules (paths and model): [SKILLS_AND_RULES.md](SKILLS_AND_RULES.md).
- Release and publish are handled by this repo's automatic versioning hooks and GitHub workflow.

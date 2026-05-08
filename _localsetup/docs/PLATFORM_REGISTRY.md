---
status: ACTIVE
version: 3.0
---

# Platform registry (Localsetup v3)

**Purpose:** Single source of truth for which AI agent platforms the framework supports. When you need to list supported platforms, reference this file instead of scattering names across docs. When adding a new platform, add it here first; when registering a new skill, use the "Skill registration (new skills)" list below so no platform is missed.

**Manifest source:** V3 installer behavior is controlled by `_localsetup/config/platforms.yaml`. This page is a human-readable summary. The root `--tools` flag remains a compatibility alias for v3 `--platforms`.

## Supported platforms

| ID | Display name | Repo adapter path | Managed skill library |
|----|--------------|-------------------|-----------------------|
| cursor | Cursor | .cursor/skills | ~/.local/share/agents/skills/localsetup |
| claude-code | Claude Code | .claude/skills | ~/.local/share/agents/skills/localsetup |
| codex | OpenAI Codex CLI | .codex/skills | ~/.local/share/agents/skills/localsetup |
| openclaw | OpenClaw | .openclaw/skills | ~/.local/share/agents/skills/localsetup |
| kilo | Kilo CLI | .kilo/skills | ~/.local/share/agents/skills/localsetup |
| opencode | OpenCode CLI | .opencode/skills | ~/.local/share/agents/skills/localsetup |

*More platforms may be added later. Update this table and the "Skill registration (new skills)" section when adding one.*

## Shared home library

V3 installs selected skills to `~/.local/share/agents/skills/localsetup` and attaches repo adapter paths to that library by symlink. `--mode portable` creates managed copies instead. Rollback uses `localsetup.lock.json` and removes only managed paths.

## Skill registration (new skills)

When adding a new framework skill, register it in **every** file below so the skill appears in each platform’s context and in the framework README. Paths are relative to the **framework source root** (the directory that contains `templates/`, `skills/`, `docs/`).

Add one row or bullet per new skill with a short "When to use" description. Use the same phrasing everywhere.

| Platform / scope | File to update |
|-----------------|----------------|
| Cursor (templates) | _localsetup/templates/cursor/localsetup-context-index.md |
| Cursor (templates) | _localsetup/templates/cursor/localsetup-context.mdc |
| Claude Code | _localsetup/templates/claude-code/CLAUDE.md |
| Codex | _localsetup/templates/codex/AGENTS.md |
| OpenClaw | _localsetup/templates/openclaw/OPENCLAW_CONTEXT.md |
| OpenCode | _localsetup/templates/opencode/AGENTS.md |
| Kilo (templates) | _localsetup/templates/kilo/instructions.md |
| Framework README | _localsetup/README.md (Skills table) |
| Context skill (source) | _localsetup/skills/localsetup-context/SKILL.md |

**If you add a new platform:** extend the Supported platforms table above, add the platform’s context/skills paths, and add the corresponding registration file(s) to this table so the skill-creator and maintainers keep all platforms in sync.

## Reference

- V3 CLI: `_localsetup/tools/localsetup_v3.py plan|install|verify|rollback`.
- Root wrapper: `./install --directory . --yes`; use `--tools cursor,codex` or `--platforms cursor codex` to select adapters.
- Windows: WSL2-only. `install.ps1` is a guidance stub, not a native installer.
- Skills and rules (paths and model): [SKILLS_AND_RULES.md](SKILLS_AND_RULES.md).
- Release and publish (including packaging and sync checks) are maintained in a separate maintainer repository.

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

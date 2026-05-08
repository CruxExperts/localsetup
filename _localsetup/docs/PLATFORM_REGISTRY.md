---
status: ACTIVE
version: 2.12
---

# Platform registry (Localsetup v2)

**Purpose:** Single source of truth for which AI agent platforms the framework supports. When you need to list supported platforms, reference this file instead of scattering names across docs. When adding a new platform, add it here first; when registering a new skill, use the "Skill registration (new skills)" list below so no platform is missed.

**Deploy flag:** The install/deploy scripts use platform **IDs** (e.g. `cursor`, `claude-code`, `codex`, `openclaw`, `kilo`, `opencode`) in the `--tools` / `-Tools` option. Values must match the **ID** column.

## Supported platforms

| ID | Display name | Context loader (path in client repo) | Skills path (path in client repo) | Memory file |
|----|--------------|--------------------------------------|------------------------------------|-------------|
| cursor | Cursor | .cursor/rules/localsetup-context.mdc (and .cursor/rules/localsetup-context-index.md) | .agents/skills/localsetup-*/ (with .cursor/skills compatibility link) | .cursor/rules/agent-memory.md |
| claude-code | Claude Code | .claude/CLAUDE.md | .agents/skills/localsetup-*/ (with .claude/skills compatibility link) | .claude/AGENT_MEMORY.md |
| codex | OpenAI Codex CLI | AGENTS.md (repo root) | .agents/skills/localsetup-*/ (with .codex/skills compatibility link) | .agents/AGENT_MEMORY.md |
| openclaw | OpenClaw | [OPENCLAW_CONTEXT.md](../templates/openclaw/OPENCLAW_CONTEXT.md) (merge into workspace MEMORY.md if desired) | skills/localsetup-*/ (repo root) | AGENT_MEMORY.md (repo root) |
| kilo | Kilo CLI | .kilo/instructions.md | .agents/skills/localsetup-*/ (with .kilo/skills compatibility link) | .kilo/AGENT_MEMORY.md |
| opencode | OpenCode CLI | AGENTS.md (repo root) | .agents/skills/localsetup-*/ (with .opencode/skills compatibility link) | .opencode/AGENT_MEMORY.md |

*More platforms may be added later. Update this table and the "Skill registration (new skills)" section when adding one.*

## Global deployment (user-wide, cross-project)

When deployed with `--scope global` (via `./install --global` or `install.ps1 -Global`), the framework installs skills and rules to user-wide locations. This makes the framework available across all projects without per-repo installation.

| Platform | Global skills path | Memory file | Global config | Notes |
|----------|-------------------|-------------|---------------|-------|
| codex | `$CODEX_HOME/skills/` or `~/.codex/skills/` | `$CODEX_HOME/AGENT_MEMORY.md` or `~/.codex/AGENT_MEMORY.md` | N/A | User-level Codex CLI skills |
| kilo | `~/.config/kilo/skills/` | `~/.config/kilo/AGENT_MEMORY.md` | `~/.config/kilo/kilo.json` or `kilo.jsonc` | Skills auto-discovered by Kilo |
| openclaw | `~/.openclaw/skills/` | `~/.openclaw/AGENT_MEMORY.md` | `~/.openclaw/openclaw.json` | Skills auto-discovered |
| claude-code | `~/.claude/skills/` | `~/.claude/AGENT_MEMORY.md` | N/A | Uses `~/.claude/CLAUDE.md` for global context |
| opencode | `~/.config/opencode/skills/` | `~/.config/opencode/AGENT_MEMORY.md` | N/A | Skills auto-discovered |

**Precedence:** Repo-local deployment wins over global. Project-local skills/rules override global ones, allowing projects to customize without affecting the global install.

**Kilo-specific:** Global skills go to `~/.config/kilo/skills/` which Kilo auto-discovers. Memory file goes to `~/.config/kilo/AGENT_MEMORY.md`. Context file is deployed to `~/.config/kilo/instructions/localsetup.md` and is idempotently added to the `instructions[]` array in `kilo.json`/`kilo.jsonc`. This is a one-time setup; subsequent global deploys update the skill and context files.

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

- Deploy script: `_localsetup/tools/deploy` (Bash) / `deploy.ps1` (PowerShell); accepts `--tools "cursor,claude-code,codex,openclaw,kilo,opencode"` and `--scope local|global`.
- Global install: root `install` (Bash) / `install.ps1` (PowerShell) with `--global` / `-Global` flag. Auto-detects installed agents (kilo, openclaw, claude). Skills go to `~/.config/kilo/skills/` (auto-discovered), context goes to `~/.config/kilo/instructions/localsetup.md`.
- Skills and rules (paths and model): [SKILLS_AND_RULES.md](SKILLS_AND_RULES.md).
- Release and publish (including packaging and sync checks) are maintained in a separate maintainer repository.

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

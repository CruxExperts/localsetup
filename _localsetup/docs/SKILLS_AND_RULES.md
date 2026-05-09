---
status: ACTIVE
version: 3.0
---

# Skills And Rules (Localsetup v3)

**Purpose:** How the master rule (or platform context loader) and skills interact; when to load which skill; cross-platform paths.

## Model

- **One always-loaded context** per platform: Cursor uses `.cursor/rules/ls-context.mdc`; Claude Code uses `.claude/CLAUDE.md`; Codex uses `AGENTS.md`; OpenClaw uses its platform template; OpenCode uses `AGENTS.md`; Kilo CLI uses `.kilo/instructions.md`.
- **Skills:** Same `SKILL.md` source content works across platforms. Canonical source lives in `_localsetup/skills/`; v3 installs managed copies to `~/.local/share/agents/skills/localsetup`; repo adapter paths such as `.codex/skills`, `.cursor/skills`, `.claude/skills`, `.opencode/skills`, `.openclaw/skills`, and `.kilo/skills` attach to that managed library by symlink or portable copy.
- **Memory file:** Each platform has a writable memory file for agent learnings (`.kilo/AGENT_MEMORY.md`, `.claude/AGENT_MEMORY.md`, etc.). See [MEMORY_MANAGEMENT.md](MEMORY_MANAGEMENT.md) for curation rules.
- **When to load a skill:** Load when the task matches the skill's description (e.g. user says "decision tree" -> ls-decision-tree-workflow). The master rule/context includes an index of skills and when to use them.

## Task-to-skill matching flow

- **Mode detection:** Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- **Named skill override:** If user names a specific skill, load that skill directly. Do not run task-skill-matcher.
- **When to invoke matcher:** When uncertain which skill fits, or when user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task behavior:** If one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from [PUBLIC_SKILL_INDEX.yaml](PUBLIC_SKILL_INDEX.yaml) (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before complementary suggestions.
- **Batch behavior:** Prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, state the planned skill sequence first, then proceed without repeated skill prompts.
- **No installed fit:** Say that no installed skill fits, offer up to 3 complementary public skills to import, and optionally suggest creating a skill via `ls-skill-creator`.
- **Reference:** Full procedure and output format live in skill `ls-task-skill-matcher` and [TASK_SKILL_MATCHING.md](TASK_SKILL_MATCHING.md).

## Platform paths

**Canonical list:** Supported platforms and their context/skills/memory paths are defined in [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md). Reference that file when listing platforms or adding a new one. Summary:

| Platform | Context loader | Skills | Memory file |
|----------|----------------|--------|-------------|
| Cursor | .cursor/rules/ls-context.mdc | .cursor/skills -> managed library | .cursor/rules/agent-memory.md |
| Claude Code | .claude/CLAUDE.md | .claude/skills -> managed library | .claude/AGENT_MEMORY.md |
| Codex | AGENTS.md (repo root) | .codex/skills -> managed library | .agents/AGENT_MEMORY.md |
| OpenClaw | platform template | .openclaw/skills -> managed library | AGENT_MEMORY.md (repo root) |
| OpenCode | AGENTS.md (repo root) | .opencode/skills -> managed library | .opencode/AGENT_MEMORY.md |
| Kilo CLI | .kilo/instructions.md | .kilo/skills -> managed library | .kilo/AGENT_MEMORY.md |

## Format

- Skills follow the [Agent Skills](https://agentskills.io/specification) specification: SKILL.md with required `name` and `description` frontmatter; optional `metadata.version` for skill document versioning; body = instructions. Same files work on all platforms.
- **Skill document versioning:** Each skill includes `metadata.version` (e.g. `"1.0"`). Skill versions are tracked separately from the framework release version; see [AGENT_SKILLS_COMPLIANCE.md](AGENT_SKILLS_COMPLIANCE.md).
- When adding a platform or registering a new skill, use [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md) as the source of truth.
- **Interoperability:** Skills are [Agent Skills](https://agentskills.io/specification)-compliant and interchangeable: our skills work in any spec-compliant host; external skills (e.g. [Anthropic's](https://github.com/anthropics/skills)) can be used here with placement + registration. See [SKILL_INTEROPERABILITY.md](SKILL_INTEROPERABILITY.md).

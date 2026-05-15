---
status: ACTIVE
version: 4.0
---

# Memory Management (Localsetup v3)

**Purpose:** How to use the persistent memory file for AI agent learnings, with strict curation to prevent file bloat.

## Overview

Localsetup v3 includes a persistent **memory file** for each supported platform. This memory file stores AI agent learnings, patterns, and troubleshooting solutions across sessions. Memory files are mutable project or platform state; they are not framework source and must not be stored under `_localsetup/`.

## Framework-Owned Boundary

`_localsetup/` is framework-owned source: code, docs, skills, workflow packages, templates, and generated framework artifacts. Upgrades may replace this folder. Do not store reminders, backlog entries, agent memory, temporary notes, heartbeat runtime output, or other mutable project/user state under `_localsetup/`.

Mutable project or user state belongs in stable repo-level paths such as platform memory files, harness state directories, or platform-owned home paths declared in `platforms.yaml`. If mutable state is accidentally placed under `_localsetup/`, move it to an approved path and revert the framework-source change.

## Core Principle: Curation Over Accumulation

Memory files **must remain curated and concise**. Without active curation, these files grow unbounded and become useless. The following rules are enforced:

### Curation Rules (Mandatory)

| Rule | Description |
|------|-------------|
| **Maximum 20 entries per section** | When exceeded, remove oldest/least relevant entries first |
| **Revise, don't append** | Update existing entries rather than adding new ones |
| **Stale = removed** | Entries older than 30 days without reaffirmation are deleted |
| **Quality over quantity** | Only record patterns confirmed in 2+ sessions |
| **Escalate significant learnings** | Put important patterns in framework docs, not just memory |

## Memory File Locations

Each platform has its own memory file location:

| Platform | Memory File Location | Context File |
|----------|---------------------|--------------|
| **Kilo CLI** | `.kilo/MEMORY.md` | `.kilo/instructions.md` |
| **OpenCode CLI** | `.opencode/MEMORY.md` | `AGENTS.md` (repo root) |
| **Claude Code** | `.claude/MEMORY.md` | `.claude/CLAUDE.md` |
| **Codex CLI** | `.agents/MEMORY.md` | `AGENTS.md` (repo root) |
| **Cursor** | `.cursor/rules/MEMORY.md` | `.cursor/rules/ls-context.mdc` |
| **OpenClaw** | `MEMORY.md` (repo root) | `OPENCLAW_CONTEXT.md` |

## Memory File Structure

Each memory file contains:

```markdown
# Memory [Platform]

This file stores AI agent learnings as mutable project/platform state outside `_localsetup/`.
It must remain CURATED and CONCISE. Bloat will be corrected.

## Curation Rules (MUST Follow)

1. **Maximum 20 entries per section** - When exceeded, remove oldest/least relevant
2. **Revise, don't append** - Update existing entries rather than adding new ones
3. **Stale = removed** - Entries older than 30 days without reaffirmation are deleted
4. **Quality over quantity** - Only record patterns confirmed in 2+ sessions
5. **Escalate significant learnings** - Put important patterns in framework docs, not here

## Framework Learnings
- [Date] [Pattern] - [Why it's effective]

## Project Patterns
- [Date] [Convention] - [Context where it applies]

## Troubleshooting Log
- [Date] [Problem] - [Solution]

## Improvement Suggestions
- [Date] [Suggestion] - [Rationale]
```

## Memory Management Flow

When you discover something valuable:

1. **Check before writing** - Does this pattern already exist?
2. **Be specific** - Good: `- 2026-04-02: Use ruff format before ruff check`
3. **Quality gate** - Only record patterns confirmed in 2+ sessions
4. **Curate actively** - Before adding, remove stale entries
5. **Escalate** - Move important patterns to framework docs
6. **No bloat** - If section exceeds 20 entries, remove old ones first

## What to Record

### Good candidates for memory:
- **Confirmed patterns** observed across 2+ sessions
- **Effective conventions** specific to this project
- **Troubleshooting solutions** that worked
- **Tool preferences** discovered through experience

### Poor candidates (put in framework docs instead):
- Universal best practices (not project-specific)
- Security policies
- Patterns that should be documented as invariants
- Anything that belongs in `AGENTS.md` or skill files

## Deployment: V3 Memory Paths

V3 declares memory paths in `_localsetup/config/platforms.yaml`. The installer focuses on managed skill adapters; memory files remain project or platform state outside `_localsetup/` and should stay curated by the agent host using them.

### Repo-local memory

- Each project can keep its own isolated memory where the platform expects it.
- Repo-local memory may be versioned only when it contains no secrets or private state.
- Project-specific memory takes precedence for that project.

### Home-scoped memory

Home-scoped memory paths are allowed only under `~/` in `platforms.yaml`. They are useful for durable user-level conventions, but must not contain repo secrets or generated private state.

| Platform | Default memory path |
|----------|------------------|
| Codex | `~/.codex/memories` |
| Claude Code | `~/.claude/memories` |
| Cursor | `~/.cursor/memories` |
| Kilo CLI | `~/.kilo/memories` |
| OpenCode CLI | `~/.opencode/memories` |
| OpenClaw | `~/.openclaw/memories` |

## Platform-Specific Notes

### Kilo CLI

Kilo CLI uses `.kilo/instructions.md` at repo root for framework context (local deploy) or `~/.config/kilo/instructions/localsetup.md` (global deploy). The repo-local memory file is at `.kilo/MEMORY.md`. Home-scoped memory uses the `~/.kilo/memories` root declared in `platforms.yaml`.

**Setup for memory loading:** No additional configuration is required. The deploy script idempotently adds the context file to your `instructions[]` in `kilo.json`/`kilo.jsonc`.

### Cursor

Cursor uses `.cursor/rules/MEMORY.md`. The context file references this automatically.

### Claude Code

Claude Code uses `.claude/MEMORY.md`. The `CLAUDE.md` context file references this automatically.

## Integration with Context Files

Each platform's context file (AGENTS.md, CLAUDE.md, etc.) includes a reference to its memory file and the curation rules. The AI agent is prompted to:

1. Check the memory file at session start
2. Update it with new learnings
3. Curate before adding (remove stale entries)
4. Escalate significant patterns to framework docs

## See Also

- [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md) - Platform paths and memory file locations
- [MULTI_PLATFORM_INSTALL.md](MULTI_PLATFORM_INSTALL.md) - Deployment options including global
- [SKILLS_AND_RULES.md](SKILLS_AND_RULES.md) - How context and skills interact

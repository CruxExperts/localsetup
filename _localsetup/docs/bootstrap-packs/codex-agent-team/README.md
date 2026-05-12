---
status: ACTIVE
version: 3.3
---

# Codex Agent Team Bootstrap Pack

This pack captures the Codex-first controller/subagent workflow used to audit and maintain a global Codex agent-team bootstrap.

It is intentionally native to Codex:

- `$CODEX_HOME/config.toml` or `~/.codex/config.toml`
- `$CODEX_HOME/AGENTS.md` or `~/.codex/AGENTS.md`
- `$CODEX_HOME/agents/*.toml` or `~/.codex/agents/*.toml`
- repo `AGENTS.md`
- native subagents
- plan mode and goal mode
- markdown runbooks and small YAML metadata

## Localsetup Pack

Install or select the pack as `bootstrap`. The source membership lives in [`_localsetup/config/pack.yaml`](../../../config/pack.yaml), and the generated index lives in [`_generated/skill-packs.md`](../../_generated/skill-packs.md).

The pack composes existing Localsetup skills and workflow packages instead of copying their instructions:

- controller context and communication
- framework compliance and docs routing
- safety and guarded operations
- test and review support
- audit and git-repair workflows

## Prompt

Use [AUDIT_PROMPT.md](AUDIT_PROMPT.md) when asking Codex to audit a prior global bootstrap and produce durable artifacts.

## Approval Boundary

This pack may inspect global Codex state, but changes to home-directory files, sibling repos, global permissions, or external runtime mirrors require explicit user approval.

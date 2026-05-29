---
status: ACTIVE
version: 4.0
owner_skill: ls-framework-compliance
---

# Codex Agent Team Bootstrap Pack

This pack captures the generic Codex controller/subagent workflow used to audit and maintain a global Codex agent-team bootstrap.

It is intentionally native to Codex:

- `$CODEX_HOME/config.toml` or `~/.codex/config.toml`
- `$CODEX_HOME/AGENTS.md` or `~/.codex/AGENTS.md`
- `$CODEX_HOME/agents/*.toml` or `~/.codex/agents/*.toml`
- repo `AGENTS.md`
- native subagents
- plan mode and goal mode
- markdown runbooks and small YAML metadata

The default is throughput-oriented, not specialist-heavy: the controller keeps task units small, uses direct mode for obvious small work, and delegates only when a scoped subtask is independent or clearly bounded. Normal fanout is one or two agents; three is reserved for clearly independent discovery, research, or validation. Existing native roles stay generic:

- `explorer`: read-only mapping of relevant files, systems, docs, workflows, data, dependencies, tests, and risks
- `researcher`: current or source-backed fact verification
- `worker`: one bounded execution task with exact write scope
- `tester`: validation, benchmarks, measurements, and failure summaries
- `reviewer`: final risk, correctness, regression, scope, and evidence review

## Localsetup Pack

Install or select the pack as `bootstrap`. The source membership lives in [`_localsetup/config/pack.yaml`](../../../config/pack.yaml), and the generated index lives in [`_generated/skill-packs.md`](../../_generated/skill-packs.md).

The pack composes existing Localsetup skills and workflow packages instead of copying their instructions:

- controller context and communication
- framework compliance and docs routing
- safety and guarded operations
- test and review support
- audit and git-repair workflows

## Prompt

Use [AUDIT_PROMPT.md](AUDIT_PROMPT.md) when asking Codex to audit a prior global bootstrap or refresh the durable generic controller defaults.

## Approval Boundary

This pack may inspect global Codex state, but changes to home-directory files, sibling repos, global permissions, or external runtime mirrors require explicit user approval.

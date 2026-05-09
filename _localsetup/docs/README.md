---
status: ACTIVE
version: 3.0
---

# Framework Docs Index

This is the public documentation map for Localsetup v3. Start here when you want the install path, platform behavior, shipped skills, workflow model, or release/verification rules.

<p align="center">
  <img src="../../assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, config resolver, managed home library, adapters, and rollback metadata" width="960">
</p>

## Generated Facts

<!-- facts-block:start -->
- Current version: `3.0.1`
- Supported platforms: `cursor, claude-code, codex, openclaw, kilo, opencode`
- Shipped skills: `49`
- Source: `_localsetup/docs/_generated/facts.json`
<!-- facts-block:end -->

## Start Here

| Page | What it answers |
|---|---|
| [Project README](../../README.md) | Why Localsetup exists and why people should use it. |
| [Quickstart](QUICKSTART.md) | How to install, select platforms, verify, and update. |
| [Features](FEATURES.md) | Full capability catalog grouped by practical use. |
| [Shipped skills catalog](SKILLS.md) | All shipped skills with IDs, versions, and descriptions. |
| [Platform registry](PLATFORM_REGISTRY.md) | Canonical platform IDs, paths, and adapter rules. |
| [Multi-platform install](MULTI_PLATFORM_INSTALL.md) | Detailed install behavior and options. |

## Core Workflows

| Page | What it covers |
|---|---|
| [Workflow registry](WORKFLOW_REGISTRY.md) | Named workflows, aliases, impact expectations, and when to use them. |
| [Workflow quick reference](WORKFLOW_QUICK_REF.md) | Agent-facing workflow shortcuts and composite pipelines. |
| [Decision tree workflow](DECISION_TREE_WORKFLOW.md) | Reverse-prompt planning: one question, options, preferred choice, rationale. |
| [PRD schema and external agent guide](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) | Spec format, outcome template, and external-agent handoff fields. |
| [Git traceability](GIT_TRACEABILITY.md) | How PRDs, specs, outcomes, and commits stay connected. |
| [Tmux ops remote guide](ops/tmux-ops-remote.md) | How to run human-visible ops when tmux is on another host. |

## Skills

| Page | What it covers |
|---|---|
| [Skills and rules](SKILLS_AND_RULES.md) | How always-loaded context, skills, adapters, and memory fit together. |
| [Agent Skills compliance](AGENT_SKILLS_COMPLIANCE.md) | How Localsetup implements the Agent Skills spec. |
| [Skill importing](SKILL_IMPORTING.md) | Import skills from URLs or local paths with validation and screening. |
| [Skill discovery](SKILL_DISCOVERY.md) | Public skill registry/index workflow and recommendations. |
| [Skill interoperability](SKILL_INTEROPERABILITY.md) | How skills move between Localsetup and spec-compatible hosts. |
| [Skill normalization](SKILL_NORMALIZATION.md) | How imported or in-tree skills are cleaned up and standardized. |
| [Task skill matching](TASK_SKILL_MATCHING.md) | How agents choose the right skill for a task. |

## Agent Q Transport

Agent Q is the bidirectional handoff layer for PRD/spec exchange over file_drop or mail with sealed payloads, registry checks, and ledgered outcomes.

| Page | What it covers |
|---|---|
| [Agent-to-agent protocol](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) | Transport principles, flows, pre-ship checks, and PRD field mapping. |
| [Agent Q scenarios](AGENTIC_AGENT_Q_SCENARIOS.md) | Same-machine, multi-repo, local/remote, mail, and file_drop scenarios. |
| [Agent Q build spec](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) | Implementation order and backlog for the transport client. |
| [Agent Q pattern](AGENTIC_AGENT_Q_PATTERN.md) | Queue layout and PRD file movement model. |

## Maintenance And Release

| Page | What it covers |
|---|---|
| [Versioning](VERSIONING.md) | VERSION source of truth, Conventional Commits, and release sync. |
| [Document lifecycle](DOCUMENT_LIFECYCLE_MANAGEMENT.md) | ACTIVE, DRAFT, PROPOSAL, and deprecation rules. |
| [Repo and data separation](REPO_AND_DATA_SEPARATION.md) | What belongs in source vs. local/generated state. |
| [Tooling policy](TOOLING_POLICY.md) | Python-first tooling expectations and public docs constraints. |

## Public Project Links

- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)
- [License](../../LICENSE)

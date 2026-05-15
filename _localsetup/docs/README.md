---
status: ACTIVE
version: 3.8
---

# Framework Docs Index

This is the public documentation map for Localsetup v3. Start here when you want the install path, platform behavior, shipped skills, workflow model, or release/verification rules.

<p align="center">
  <img src="../../assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, config resolver, managed home library, adapters, and rollback metadata" width="960">
</p>

## Generated Facts

<!-- facts-block:start -->
- Current version: `3.8.5`
- Supported platforms: `cursor, claude-code, codex, openclaw, kilo, opencode`
- Shipped skills: `52`
- Workflow packages: `22`
- Source: `_localsetup/docs/_generated/facts.json`
<!-- facts-block:end -->

## Start Here

| Page | What it answers |
|---|---|
| [Project README](../../README.md) | Why Localsetup exists and why people should use it. |
| [Quickstart](QUICKSTART.md) | How to install, select platforms, verify, and update. |
| [Features](FEATURES.md) | Full capability catalog grouped by practical use. |
| [Shipped skills catalog](SKILLS.md) | All shipped skills with IDs, versions, and descriptions. |
| [Bootstrap packs](bootstrap-packs/INDEX.md) | Reusable Codex-first bootstrap prompts, pack metadata, audit boundaries, and future adapter entry points. |
| [Workflow packages](WORKFLOW_PACKAGES.md) | How workflow packages differ from skills, install, validate, and generate docs. |
| [Workflow package standard](WORKFLOW_STANDARD.md) | Rules for first-class workflow packages and `workflow.yaml`. |
| [Platform registry](PLATFORM_REGISTRY.md) | Canonical platform IDs, paths, and adapter rules. |
| [Multi-platform install](MULTI_PLATFORM_INSTALL.md) | Detailed install behavior and options. |
| [Harness automation](HARNESS_AUTOMATION.md) | Opt-in Codex heartbeat activation, runtime artifacts, cron gating, and command-policy boundaries. |

## Skills And Workflow Packages At A Glance

Localsetup installs both capability skills and workflow packages into the managed package library. Keep [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md) as the canonical reference for:

- source layout and runtime shape
- installer behavior and dependency pull-in
- validation and generated workflow docs

## Core Workflows

| Page | What it covers |
|---|---|
| [Workflow registry](WORKFLOW_REGISTRY.md) | Named workflows, aliases, impact expectations, and when to use them. |
| [Workflow quick reference](WORKFLOW_QUICK_REF.md) | Agent-facing workflow shortcuts and composite pipelines. |
| [Decision tree workflow](DECISION_TREE_WORKFLOW.md) | Reverse-prompt planning: one question, options, preferred choice, rationale. |
| [PRD schema and external agent guide](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) | Spec format, outcome template, and external-agent handoff fields. |
| [Git traceability](GIT_TRACEABILITY.md) | How PRDs, specs, outcomes, and commits stay connected. |
| [Tmux ops managed workflow](ops/tmux-ops-managed.md) | Human and agent guide for managed tmux sessions, sudo probe, run IDs, logs, status, and cancellation. |
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

Registered capability highlights:

- `ls-nodejs-nextjs`: Node.js/Next.js/React runbook for package-manager, build, migration, debugging, testing, security, deployment, and current-version verification.
- `ls-github-starredrepos`: GitHub starred repository archive workflow for authenticated context checks, dry-run sync, repo scouting, metadata snapshots, and guarded publish flows.
- `ls-shadcn-ui`: shadcn/ui component workflow for setup, components, CLI/MCP, registry, theming, forms, aliases, Radix/Base UI, updates, and troubleshooting.
- `ls-typescript-code-quality`: TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code.

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
| [Documentation alignment summary](_generated/docs-alignment-summary.md) | Generated inventory, truth map, asset manifest, and docs-alignment audit results. |
| [Harness automation](HARNESS_AUTOMATION.md) | Explicit activation rules for autonomous harness capabilities. |
| [Repository maintenance](REPO_MAINTENANCE.md) | GitHub rulesets, required checks, labels, triage, security settings, and release-maintenance gates. |
| [Document lifecycle](DOCUMENT_LIFECYCLE_MANAGEMENT.md) | ACTIVE, DRAFT, PROPOSAL, and deprecation rules. |
| [Repo and data separation](REPO_AND_DATA_SEPARATION.md) | What belongs in source vs. local/generated state. |
| [Tooling policy](TOOLING_POLICY.md) | Python-first tooling expectations and public docs constraints. |

## Public Project Links

- [Contributing](../../CONTRIBUTING.md)
- [Security](../../SECURITY.md)
- [Support](../../SUPPORT.md)
- [Code of conduct](../../CODE_OF_CONDUCT.md)
- [License](../../LICENSE)

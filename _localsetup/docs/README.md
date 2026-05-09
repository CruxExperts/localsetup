---
status: ACTIVE
version: 3.0
---

# 📚 Framework docs index

This is the public documentation index for Localsetup v3. Use it to navigate framework behavior, skills, platform support, and agentic workflows.

<p align="center">
  <img src="../../assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, resolved config, managed home library, adapters, and rollback metadata" width="960">
</p>

## 📊 Generated facts

<!-- facts-block:start -->
- Current version: `3.0.1`
- Supported platforms: `cursor, claude-code, codex, openclaw, kilo, opencode`
- Shipped skills: `49`
- Source: `_localsetup/docs/_generated/facts.json`
<!-- facts-block:end -->

---

## 🚀 Start here

New to Localsetup? Read these first.

| Page | What it covers |
|---|---|
| [Quickstart](QUICKSTART.md) | Installation, platform selection, verification, one-liners for CI |
| [Features](FEATURES.md) | Full capability catalog with tables for every feature category |
| [Shipped skills catalog](SKILLS.md) | All shipped skills with IDs, descriptions, and versions |
| [Platform registry](PLATFORM_REGISTRY.md) | Canonical table of platform IDs, context paths, and skills paths |
| [Multi-platform install](MULTI_PLATFORM_INSTALL.md) | Detailed cross-platform deployment instructions |

---

## 🔄 Core workflow docs

How agentic workflows operate inside this framework.

| Page | What it covers |
|---|---|
| [Agentic design index](AGENTIC_DESIGN_INDEX.md) | Index of agentic design documents |
| [Workflow registry](WORKFLOW_REGISTRY.md) | Named workflows, when to use them, Workflow IDs and aliases, impact review expectations |
| [Workflow quick reference](WORKFLOW_QUICK_REF.md) | Agent-facing workflow IDs, names, aliases, common-phrase mapping, and composite pipelines (PR feedback loop, git repair and hygiene, server triage and patch, repo polish) |
| [Decision tree workflow](DECISION_TREE_WORKFLOW.md) | Reverse-prompt process: one question, four options, preferred + rationale |
| [PRD schema and external agent guide](PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) | Spec format for PRDs, outcome template, and how PRDs interact with bidirectional Agent Q |
| [Git traceability](GIT_TRACEABILITY.md) | Linking PRDs, specs, and outcomes to git commits |
| [Tmux ops (remote)](ops/tmux-ops-remote.md) | Use tmux_ops when tmux runs on another host (REMOTE_TMUX_HOST, REMOTE_TMUX_CWD) |

---

## Agent Q transport (bidirectional handoff)

Agent-to-agent PRD exchange over file_drop or mail; OpenPGP sealed blobs; registry and ledger.

| Page | What it covers |
|---|---|
| [Agent-to-agent protocol](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) | Principles, flows, pre-ship, version stamp, and how transport interprets PRD fields like `ack_required`, `delivery`, `deliverable`, `conversation_id`, `iteration` |
| [Agent Q scenarios](AGENTIC_AGENT_Q_SCENARIOS.md) | Same machine / different repos, local vs remote, mail vs file_drop, agent decision guide, and how transports behave across deployments |
| [Agent Q build spec](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) | Implementation build order and backlog for the transport client (Part 19 backlog; see DEFERRED.md) |
| [Agent Q pattern](AGENTIC_AGENT_Q_PATTERN.md) | Queue layout inbox/in/out/pending/archive and how the batch walks PRDs on disk |
| Client [USER_GUIDE](../tools/agentq_transport_client/docs/USER_GUIDE.md) | agentq_cli commands |
| Client [ADMIN_GUIDE](../tools/agentq_transport_client/docs/ADMIN_GUIDE.md) | Policy, rotation, force ingest |

Skill: **ls-agentq-transport** (see [SKILLS.md](SKILLS.md)).

---

## 🛠️ Skills docs

How to use, import, create, and vet skills.

| Page | What it covers |
|---|---|
| [Skills and rules](SKILLS_AND_RULES.md) | Relationship between skills and Cursor rules |
| [Skill importing](SKILL_IMPORTING.md) | Import skills from URL or local path with validation |
| [Skill discovery](SKILL_DISCOVERY.md) | Public registry index and recommendations for similar skills |
| [Skill interoperability](SKILL_INTEROPERABILITY.md) | Agent Skills spec compliance and cross-ecosystem compatibility |
| [Skill normalization](SKILL_NORMALIZATION.md) | Phase 1: documents (platform choice when platform-specific); Phase 2: tooling rewrite to framework standard. Spec compliance and platform handling. |
| [Task skill matching](TASK_SKILL_MATCHING.md) | Match incoming tasks to installed skills |

---

## 🖥️ Platform and compliance docs

Supported platforms, repo/data separation, and document lifecycle.

| Page | What it covers |
|---|---|
| [Platform registry](PLATFORM_REGISTRY.md) | Canonical source for platform IDs and paths |
| [Agent Skills compliance](AGENT_SKILLS_COMPLIANCE.md) | How this framework implements the Agent Skills spec |
| [Repo and data separation](REPO_AND_DATA_SEPARATION.md) | Engine vs. repo-local data boundaries |
| [Document lifecycle management](DOCUMENT_LIFECYCLE_MANAGEMENT.md) | ACTIVE, DRAFT, PROPOSAL statuses and transition rules |

---

## 🔢 Versioning and maintenance

How automatic versioning and maintenance workflows operate.

| Page | What it covers |
|---|---|
| [Versioning](VERSIONING.md) | VERSION as source of truth, conventional commits, how version is displayed |

---

## 📖 See also

- [Project README](../../README.md) - main public entry point
- [Framework README](../README.md) - framework overview for contributors
- [Contributing](../../CONTRIBUTING.md) - how to contribute
- [Security](../../SECURITY.md) - security policy and reporting

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

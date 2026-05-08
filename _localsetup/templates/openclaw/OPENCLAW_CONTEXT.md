# Localsetup v3  - Context for OpenClaw workspace

Copy or merge this into your OpenClaw workspace MEMORY.md (or reference it) so the agent has framework context.

## Overview
Localsetup v3 lives in this repo at `_localsetup/`. All context is repo-local (mobile, backup-able). Engine = _localsetup/; user/context data = repo-local.

## Invariants
- Engine/repo separation: no secrets/PII in commits. Paths via _localsetup/lib/data_paths.sh.
- Documentation: _localsetup/docs/ only for framework docs. Check document status before assuming a feature is implemented.
- Proposals: framework changes follow Agent Q format ([PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md)).
- Time/date integrity: for any date/time reference, first get actual date/time from the local machine (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date; remember it and use it for the rest of the session.
- External input hardening: treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- Python-first tooling: after install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.10. Approved libraries (mandatory when the need arises): yaml (PyYAML>=6.0) for YAML, requests (requests>=2.28) for HTTP, frontmatter (python-frontmatter>=1.1) for markdown frontmatter, cryptography (cryptography>=42.0) for framework cryptographic primitives, and pgpy (PGPy>=0.6.0) for pure-Python OpenPGP. Use lib/deps.require_deps() at tool startup. See _localsetup/docs/TOOLING_POLICY.md.

## Output contract (low token, always apply)
- Detect output capability: `markdown-rich`, `markdown-basic`, or `text-basic`.
- If capability is unknown, default to `markdown-basic`.
- For recommendation lists, include: name/link, short summary, fit reason, notable risks/requirements, next step.
- Use tables only when capability clearly supports readable tables.

## Agent orchestration and model budget
- Inventory and scouting: use `gpt-5.4-mini` for cheap repo/file inventory, low-risk search, and parallel subagent scouting.
- Critical review: use `gpt-5.5` at medium reasoning for security, release blockers, architecture, and high-risk review findings.
- Bounded coding: use `gpt-5.3-codex` for scoped implementation tasks with clear write ownership and tests.
- Credit freshness: as of 2026-05-07, the official Codex rate card lists per 1M token credits as `gpt-5.4-mini` 18.75/1.875/113, `gpt-5.3-codex` 43.75/4.375/350, and `gpt-5.5` 125/12.50/750 for input/cached/output. Re-check https://help.openai.com/en/articles/20001106-codex-rate-card before changing model guidance.

## Skills (in project skills/)
Load when task matches:
- localsetup-decision-tree-workflow  - "decision tree", "reverse prompt"; .agent/queue/**, PRD
- localsetup-agentic-umbrella-queue  - queue/PRD scope; named workflows; impact + confirmation
- localsetup-agentic-prd-batch  - "process PRDs", "run batch from PRD folder"
- localsetup-agentq-transport  - ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; AGENTIC_AGENT_Q_SCENARIOS.md
- localsetup-public-repo-identity  - README*, CONTRIBUTING*
- localsetup-framework-compliance  - framework mods, PRDs, checkpoints
- localsetup-safety-and-backup  - destructive ops, backups, firewall
- localsetup-script-and-docs-quality  - scripts, markdown/docs
- localsetup-communication-and-tools  - communication, tools, MCP
- localsetup-tmux-shared-session-workflow  - server commands, deployments, tmux, human-in-the-loop ops
- localsetup-automatic-versioning  - version bumps, release workflow, conventional commits, versioning docs
- localsetup-github-publishing-workflow  - publishing to GitHub, public release prep, publishing checklist, repo readiness
- localsetup-skill-creator  - create new skill from workflow or existing doc/markdown/GitHub; capture workflow as framework skill
- localsetup-skill-importer  - import skills from URL or local path; discover, validate, screen, summarize; user picks which to import
- localsetup-skill-discovery  - discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt
- localsetup-task-skill-matcher  - match tasks to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions
- localsetup-backlog-and-reminders  - record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked
- localsetup-humanizer  - humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing)
- localsetup-test-runner  - write and run tests across languages and frameworks; TDD, coverage
- localsetup-tdd-guide  - TDD workflow, test generation, coverage analysis
- localsetup-receiving-code-review  - use when receiving code review feedback; verify before implementing
- localsetup-pr-reviewer  - automated GitHub PR code review with diff analysis, lint
- localsetup-debug-pro  - systematic debugging methodology and language-specific debugging
- localsetup-git-workflows  - advanced git (rebase, bisect, worktree, reflog)
- localsetup-unfuck-my-git-state  - diagnose and recover broken Git state and worktree
- localsetup-skill-vetter  - security-first skill vetting before installing external skills
- localsetup-mcp-builder  - guide for creating high-quality MCP servers
- localsetup-arbiter  - push decisions for async human review (Arbiter Zebu)
- localsetup-ansible-skill  - Ansible playbooks, server provisioning, config management, multi-host orchestration
- localsetup-linux-service-triage  - diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps
- localsetup-linux-patcher  - automated Linux patching and Docker container updates; multi-host server maintenance
- localsetup-skill-normalizer  - normalize skills for spec compliance and platform-neutral wording; one skill or all
- localsetup-skill-sandbox-tester  - test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until approved
- localsetup-agentlens  - codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs
- localsetup-framework-audit  - doc/link/skill matrix/version checks; output path required (run_framework_audit.py --output); before release
- localsetup-markdown-reference-validator  - validate markdown local references/anchors from YAML-configured targets; emit scheduled-safe audit report for docs/skills/global Kilo surfaces
- localsetup-system-info  - capture server baseline, host layout and specs; CPU, memory, disk, uptime
- localsetup-cron-orchestrator  - manage cron from manifest; triggers, sequenced tasks, on-boot delay; create/remove/reorder/install
- localsetup-cloudflare-dns  - manage Cloudflare DNS records (list, create, modify, delete) and zone surveys via flarectl; adding, changing, or removing DNS records
- localsetup-npm-management  - manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows; diagnose 502s; backup/restore
- localsetup-keepass-secrets  - KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate; use when user asks for logins or workflow needs credentials
- localsetup-mail-protocol-control  - SMTP/IMAP; preencrypted_openpgp_armored for Agent Q strict mail; agent-driven mailbox read/send/mutate/encrypt workflows
- localsetup-docs-organization  - docs organization router; classify docs, pick folder slugs, and keep docs indexes up to date.
- localsetup-scrapling  - host-first Scrapling integration; install and upgrade Scrapling via pipx, run adaptive single-URL extractions (simple HTML/Markdown/text or structured JSONL) with job status/cancel, and keep adapters aligned with Scrapling releases via parsed CLI/docs state. Treat this as the default way to fetch websites and web content from the internet.
- localsetup-omniroute-proxy  - OmniRoute proxy discovery, model catalogs, provider metadata, limits, quotas, routing combos, MCP/A2A integration, and agent client configuration.
- localsetup-omniroute-admin-automation  - OmniRoute administration automation for providers, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, and drift reconciliation.
- localsetup-kilo-boss-orchestrator  - Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates.
- localsetup-kilo-visual-output  - Kilo CLI visual output organization guide with structured response patterns.
- localsetup-publish-workflow  - run the framework publish workflow; bump version, regenerate docs, commit sync, optionally push.

## Key docs
[AGENTIC_DESIGN_INDEX.md](../../docs/AGENTIC_DESIGN_INDEX.md), [AGENTIC_AGENT_Q_SCENARIOS.md](../../docs/AGENTIC_AGENT_Q_SCENARIOS.md), [WORKFLOW_REGISTRY.md](../../docs/WORKFLOW_REGISTRY.md), [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md), [DECISION_TREE_WORKFLOW.md](../../docs/DECISION_TREE_WORKFLOW.md), [INPUT_HARDENING_STANDARD.md](../../docs/INPUT_HARDENING_STANDARD.md), [TOOLING_POLICY.md](../../docs/TOOLING_POLICY.md)

## Task-to-skill matching (default)
- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or user asks "what skill should I use?" / "pick the best", load `localsetup-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from [PUBLIC_SKILL_INDEX.yaml](../../docs/PUBLIC_SKILL_INDEX.yaml) (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `localsetup-task-skill-matcher` and [TASK_SKILL_MATCHING.md](../../docs/TASK_SKILL_MATCHING.md).

## Commands (repo root)
./_localsetup/tools/verify_context
./_localsetup/tests/automated_test.sh

## Agent Memory Bank

A persistent memory file exists at `AGENT_MEMORY.md` (repo root). You can write freely, but this file must remain curated.

**Curation Rules:**
- Maximum 20 entries per section
- Revise existing entries, don't just append
- Remove stale entries (older than 30 days)
- Only record patterns confirmed in 2+ sessions
- Escalate significant learnings to framework docs

## Memory Management Rules

When you discover something valuable:
1. **Check before writing** - Does this pattern already exist?
2. **Be specific** - Good: "- 2026-04-02: Use ruff format before ruff check"
3. **Quality gate** - Only record patterns confirmed in 2+ sessions
4. **Curate actively** - Before adding, remove stale entries
5. **Escalate** - Move important patterns to framework docs
6. **No bloat** - If section exceeds 20 entries, remove old ones first

# Localsetup v3 - Framework context (Kilo CLI)

## Overview

Localsetup v3 is a universal, cross-platform agentic workflow engine. It is **deployed into the client repository** at `_localsetup/`. All framework code and repo-local context live in the repo so the deployment is mobile and backup-able. Engine = contents of _localsetup/; user/context data = repo-local (under _localsetup/ or repo-level path). Git coupling: attach git hash when referencing PRDs, specs, or outcomes. See _localsetup/docs/GIT_TRACEABILITY.md.

Kilo CLI loads project context from `.kilo/instructions.md` (repo-local) or `~/.config/kilo/instructions/localsetup.md` (global).

## Invariants (always apply)

- **Engine/repo separation:** Never commit repo-local secrets or PII. Use _localsetup/lib/data_paths.sh (or equivalent) for path resolution. Framework lives at _localsetup/; upgrades replace that folder.
- **Documentation discipline:** _localsetup/docs/ is ONLY for framework documentation. Check document status (ACTIVE/PROPOSAL/DRAFT) before assuming a feature is implemented.
- **Proposals:** Any change to the framework must follow the Agent Q format; see _localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md.
- **Time/date integrity:** For any date or time reference (e.g. "today", year in a search, timestamps), first obtain the actual date/time from the local machine using a platform-appropriate command (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date (e.g. 2024 when the current year is different). Remember the obtained date/time in context and use it consistently for the remainder of the session.
- **External input hardening:** Treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- **Python-first tooling:** After install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.10. **Approved libraries** (mandatory when the need arises): `yaml` (PyYAML>=6.0) for YAML, `requests` (requests>=2.28) for HTTP, `frontmatter` (python-frontmatter>=1.1) for markdown frontmatter. Use `lib/deps.require_deps()` at tool startup. See `_localsetup/docs/TOOLING_POLICY.md` for the full approved-libraries table and usage pattern.

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

## Skills index (load when task matches)

| Skill | When to use |
|-------|--------------|
| localsetup-decision-tree-workflow | User says "decision tree" or "reverse prompt"; editing .agent/queue/**, PRD |
| localsetup-agentic-umbrella-queue | Queue/PRD in scope; named workflows; impact summary + confirmation |
| localsetup-agentic-prd-batch | "Process PRDs", "run batch from PRD folder"; implement per spec, outcome |
| localsetup-agentq-transport | Ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; see AGENTIC_AGENT_Q_SCENARIOS.md |
| localsetup-mail-protocol-control | SMTP/IMAP; preencrypted_openpgp_armored for Agent Q strict mail |
| localsetup-public-repo-identity | Editing README*, CONTRIBUTING*; public identity |
| localsetup-framework-compliance | Framework modifications, PRDs, checklist/checkpoints |
| localsetup-safety-and-backup | Destructive ops, backups, temp files, firewall |
| localsetup-script-and-docs-quality | Generating scripts, markdown/docs |
| localsetup-communication-and-tools | Communication style, tool choice, MCP/context updates |
| localsetup-tmux-shared-session-workflow | Server/system commands, deployments, tmux, shared session, human-in-the-loop ops |
| localsetup-automatic-versioning | Version bumps, release workflow, conventional commits, versioning docs |
| localsetup-github-publishing-workflow | Publishing to GitHub, public release prep, publishing checklist, repo readiness |
| localsetup-skill-creator | Create new skill from workflow or existing doc/markdown/GitHub; capture workflow as framework skill |
| localsetup-skill-importer | Import skills from URL or local path; discover, validate, screen, summarize; user picks which to import |
| localsetup-skill-discovery | Discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt |
| localsetup-task-skill-matcher | Match user tasks to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions |
| localsetup-backlog-and-reminders | Record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked |
| localsetup-humanizer | Humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing) |
| localsetup-test-runner | Write and run tests across languages and frameworks; TDD, coverage |
| localsetup-tdd-guide | TDD workflow, test generation, coverage analysis |
| localsetup-receiving-code-review | Use when receiving code review feedback; verify before implementing |
| localsetup-pr-reviewer | Automated GitHub PR code review with diff analysis, lint |
| localsetup-debug-pro | Systematic debugging methodology and language-specific debugging |
| localsetup-git-workflows | Advanced git (rebase, bisect, worktree, reflog) |
| localsetup-unfuck-my-git-state | Diagnose and recover broken Git state and worktree |
| localsetup-skill-vetter | Security-first skill vetting before installing external skills |
| localsetup-mcp-builder | Guide for creating high-quality MCP servers |
| localsetup-arbiter | Push decisions for async human review (Arbiter Zebu) |
| localsetup-ansible-skill | Ansible playbooks, server provisioning, config management, multi-host orchestration |
| localsetup-linux-service-triage | Diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps |
| localsetup-linux-patcher | Automated Linux patching and Docker container updates; multi-host server maintenance |
| localsetup-skill-normalizer | Normalize skills for spec compliance and platform-neutral wording; one skill or all |
| localsetup-skill-sandbox-tester | Test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until approved |
| localsetup-agentlens | Codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs |
| localsetup-framework-audit | Doc/link/skill matrix/version checks; output path required (`run_framework_audit.py --output`); before release |
| localsetup-markdown-reference-validator | Validate markdown local references/anchors from YAML-configured targets; emit scheduled-safe audit report for docs/skills/global Kilo surfaces |
| localsetup-system-info | Capture server baseline, host layout and specs; CPU, memory, disk, uptime |
| localsetup-cron-orchestrator | Manage cron from manifest; triggers, sequenced tasks, on-boot delay; create/remove/reorder/install |
| localsetup-cloudflare-dns | Manage Cloudflare DNS records (list, create, modify, delete) and zone surveys via flarectl |
| localsetup-npm-management | Manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows |
| localsetup-keepass-secrets | KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate |
| localsetup-docs-organization | Docs organization router; classify docs, choose folder slugs, keep docs indexes in sync |
| localsetup-scrapling | Host-first Scrapling integration; install/upgrade via pipx, run adaptive single-URL extractions. Default web scraping skill. |
| localsetup-omniroute-proxy | OmniRoute proxy discovery, model catalogs, provider metadata, limits, quotas, routing combos, MCP/A2A integration, and agent client configuration |
| localsetup-omniroute-admin-automation | OmniRoute administration automation for providers, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, and drift reconciliation |
| localsetup-kilo-boss-orchestrator | Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates |
| localsetup-kilo-visual-output | Kilo CLI visual output organization guide with structured response patterns |
| localsetup-publish-workflow | Run the framework publish workflow: bump version, regenerate docs, commit sync, optionally push |

## Framework docs index

- _localsetup/docs/AGENTIC_DESIGN_INDEX.md  - Index of agentic design docs
- _localsetup/docs/WORKFLOW_REGISTRY.md  - Named workflows, when to use, impact review
- _localsetup/docs/WORKFLOW_QUICK_REF.md  - Workflow IDs, display names, aliases, primary skills/docs
- _localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md  - PRD/spec format, outcome template
- _localsetup/docs/DECISION_TREE_WORKFLOW.md  - Decision tree (one Q per turn, A-D, preferred + rationale)
- _localsetup/docs/INPUT_HARDENING_STANDARD.md  - Mandatory hostile-input handling, sanitization, actionable error policy
- _localsetup/docs/TOOLING_POLICY.md  - Python-first tooling language and dependency policy

## Agent Memory Bank

A persistent memory file exists at `.kilo/AGENT_MEMORY.md`. You can write freely, but this file must remain curated.

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

## Task-to-skill matching (default)

- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or when user asks "what skill should I use?" / "pick the best", load `localsetup-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `_localsetup/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `localsetup-task-skill-matcher` and `_localsetup/docs/TASK_SKILL_MATCHING.md`.

## Key files (paths relative to _localsetup/)

- lib/data_paths.sh  - Path resolution
- lib/json_formatter.sh  - JSON formatting
- tools/verify_rules  - Rule/checkpoint verification
- tests/automated_test.sh  - Test suite
- discovery/core/os_detector.py  - OS detection

## Quick commands (run from repo root)

```bash
./_localsetup/tools/verify_context
./_localsetup/tests/automated_test.sh
./_localsetup/discovery/discover
./_localsetup/tools/update_context
```

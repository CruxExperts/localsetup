---
name: ls-context
description: "Localsetup v3 framework context  - overview, invariants, and skills index. Load first when working in a repo that uses Localsetup v3. Use when starting work in this repo or when user asks about framework rules."
metadata:
  version: "1.5"
---

# Localsetup v3 - Framework context (skill)

## Overview
Localsetup v3 is deployed at `_localsetup/`. Framework and context are repo-local (mobile, backup-able). Engine = _localsetup/; user data = repo-local. Use Git hashes for PRDs/specs (see [GIT_TRACEABILITY.md](../../docs/GIT_TRACEABILITY.md)).

## Invariants
- **Engine/repo separation:** Never commit repo-local secrets or PII. Use _localsetup/lib/data_paths.sh (or equivalent) for path resolution. Framework lives at _localsetup/; upgrades replace that folder.
- **Documentation:** _localsetup/docs/ only for framework docs. Check document status before assuming implemented.
- **Proposals:** Framework changes follow Agent Q format (_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).
- **Time/date integrity:** For any date/time reference, first obtain actual date/time from the local machine (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date; remember it in context and use it for the rest of the session.
- **External input hardening:** Treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- **Python-first tooling:** After install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.10.

## Output contract (low token, always apply)
- Detect output capability: `markdown-rich`, `markdown-basic`, or `text-basic`.
- If unknown, default to `markdown-basic`.
- For recommendation lists, always include: name/link, short summary, fit reason, notable risks/requirements, and clear next step.
- Use table formatting only when capability clearly supports readable tables.

## Agent orchestration and model budget
- Inventory and scouting: use `gpt-5.4-mini` for cheap repo/file inventory, low-risk search, and parallel subagent scouting.
- Critical review: use `gpt-5.5` at medium reasoning for security, release blockers, architecture, and high-risk review findings.
- Bounded coding: use `gpt-5.3-codex` for scoped implementation tasks with clear write ownership and tests.
- Escalate only when uncertainty, risk, or complexity blocks the task. As of 2026-05-07, the official Codex rate card lists per 1M token credits as `gpt-5.4-mini` 18.75/1.875/113, `gpt-5.3-codex` 43.75/4.375/350, and `gpt-5.5` 125/12.50/750 for input/cached/output. Re-check https://help.openai.com/en/articles/20001106-codex-rate-card before changing model guidance.

## Skills index (load when task matches)
- ls-decision-tree-workflow  - "decision tree", "reverse prompt"; .agent/queue/**, PRD
- ls-agentic-umbrella-queue  - queue/PRD scope; named workflows; impact + confirmation
- ls-agentic-prd-batch  - "process PRDs", "run batch from PRD folder"
- ls-agentq-transport  - ship/ingest Agent Q manifests over file_drop or mail, strict encrypted mail mode, trust registry checks, and queue/archive operations
- ls-public-repo-identity  - README*, CONTRIBUTING*
- ls-framework-compliance  - framework mods, PRDs, checkpoints
- ls-safety-and-backup  - destructive ops, backups, firewall
- ls-script-and-docs-quality  - scripts, markdown/docs
- ls-communication-and-tools  - communication, tools, MCP
- ls-tmux-shared-session-workflow  - server commands, deployments, tmux, human-in-the-loop ops; sudo discovery and single-prompt gate per validity window
- ls-automatic-versioning  - version bumps, release workflow, conventional commits, versioning docs
- ls-github-publishing-workflow  - publishing to GitHub, public release prep, publishing checklist, repo readiness
- ls-skill-creator  - create new skill from workflow or existing doc/markdown/GitHub; capture workflow as framework skill
- ls-skill-importer  - import skills from URL or local path; discover, validate, screen, summarize; user picks which to import
- ls-skill-discovery  - discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt
- ls-task-skill-matcher  - match tasks to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions
- ls-backlog-and-reminders  - record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked
- ls-humanizer  - humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing)
- ls-test-runner  - write and run tests across languages and frameworks; TDD, coverage
- ls-tdd-guide  - TDD workflow, test generation, coverage analysis
- ls-receiving-code-review  - use when receiving code review feedback; verify before implementing
- ls-pr-reviewer  - automated GitHub PR code review with diff analysis, lint
- ls-debug-pro  - systematic debugging methodology and language-specific debugging
- ls-git-workflows  - advanced git (rebase, bisect, worktree, reflog)
- ls-unfuck-my-git-state  - diagnose and recover broken Git state and worktree
- ls-skill-vetter  - security-first skill vetting before installing external skills
- ls-mcp-builder  - guide for creating high-quality MCP servers
- ls-arbiter  - push decisions for async human review (Arbiter Zebu)
- ls-ansible-skill  - Ansible playbooks, server provisioning, config management, multi-host orchestration
- ls-linux-service-triage  - diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps
- ls-linux-patcher  - automated Linux patching and Docker container updates; multi-host server maintenance
- ls-skill-normalizer  - normalize skills for spec compliance and platform-neutral wording; one skill or all
- ls-skill-sandbox-tester  - test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until approved
- ls-agentlens  - codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs
- ls-framework-audit  - run doc/link/skill matrix/version checks; output user path only; before release
- ls-markdown-reference-validator  - validate markdown local references/anchors via YAML targets and emit scheduled-safe audit report
- ls-system-info  - capture server baseline, host layout and specs; CPU, memory, disk, uptime
- ls-cron-orchestrator  - manage cron from manifest; triggers, sequenced tasks, on-boot delay; create/remove/reorder/install
- ls-cloudflare-dns  - manage Cloudflare DNS records (list, create, modify, delete) and zone surveys via flarectl; adding, changing, or removing DNS records
- ls-npm-management  - manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows; diagnose 502s; backup/restore
- ls-keepass-secrets  - KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate; use when user asks for logins or workflow needs credentials
- ls-mail-protocol-control  - manage delegated SMTP/IMAP accounts with attachment-first MIME handling, chunked attachment retrieval, and full-envelope encryption/decryption tools; agent-driven mailbox read/send/mutate/encrypt workflows
- ls-docs-organization  - docs organization router; classify documentation requests, choose folder slugs, and keep docs indexes up to date.
- ls-scrapling  - host-first Scrapling integration; install and upgrade Scrapling via pipx, run single-URL extractions (simple HTML/Markdown/text or structured JSONL), and keep adapters aligned with Scrapling releases for web scraping and crawling tasks.
- ls-omniroute-proxy  - OmniRoute, OmniRoute proxy, AI gateway discovery, model catalogs, provider limits, context windows, routing combos, MCP/A2A integration, or configuring agents to use OmniRoute.
- ls-omniroute-admin-automation  - OmniRoute administration automation via Python tooling; manage providers, nodes, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, sync, resilience, and drift reconciliation with safety gates.
- ls-kilo-boss-orchestrator  - Orchestrate Kilo headless boss-worker execution with repo-local state, watchdog leases, consensus validation, and safety gates.
- ls-kilo-visual-output  - Kilo CLI visual output organization guide; structured, readable response patterns without relying on unsupported inline color control.

## Key docs
_localsetup/docs/AGENTIC_DESIGN_INDEX.md, WORKFLOW_REGISTRY.md, PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md, DECISION_TREE_WORKFLOW.md, INPUT_HARDENING_STANDARD.md, TOOLING_POLICY.md

## Task-to-skill matching (default)
- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `_localsetup/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `ls-task-skill-matcher` and `_localsetup/docs/TASK_SKILL_MATCHING.md`.

## Commands (repo root)
./_localsetup/tools/verify_context
./_localsetup/tests/automated_test.sh

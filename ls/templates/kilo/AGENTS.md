# Localsetup - Agent context (Kilo CLI)

## Overview

Localsetup is a universal, cross-platform agentic workflow engine. It is **deployed into the client repository** at `ls/`. All framework code lives in `ls/`; mutable user/context data belongs in repo-level or platform-owned paths outside `ls/`. Git coupling: attach git hash when referencing PRDs, specs, or outcomes. See [ls/docs/GIT_TRACEABILITY.md](../../docs/GIT_TRACEABILITY.md).

Kilo CLI uses `AGENTS.md` as the project initialization file at repo root.

## Invariants (always apply)

- **Engine/repo separation:** Never commit repo-local secrets or PII. Use ls/lib/data_paths.sh (or equivalent) for path resolution. Framework lives at ls/; upgrades replace that folder.
- **Documentation discipline:** ls/docs/ is ONLY for framework documentation. Check document status (ACTIVE/PROPOSAL/DRAFT) before assuming a feature is implemented.
- **Proposals:** Any change to the framework must follow the Agent Q format; see [ls/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).
- **Time/date integrity:** For any date or time reference (e.g. "today", year in a search, timestamps), first obtain the actual date/time from the local machine using a platform-appropriate command (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date (e.g. 2024 when the current year is different). Remember the obtained date/time in context and use it consistently for the remainder of the session.
- **External input hardening:** Treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- **Python-first tooling:** After install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.12. **Approved libraries** (mandatory when the need arises): `yaml` (PyYAML>=6.0) for YAML, `requests` (requests>=2.28) for HTTP, `frontmatter` (python-frontmatter>=1.1) for markdown frontmatter, `cryptography` (cryptography>=42.0) for framework cryptographic primitives, and `pgpy` (PGPy>=0.6.0) for pure-Python OpenPGP. Use `lib/deps.require_deps()` at tool startup. See `ls/docs/TOOLING_POLICY.md` for the full approved-libraries table and usage pattern.
- **Python architecture:** Python architecture: new and substantially refactored Python tooling follows ls/docs/PYTHON_ARCHITECTURE_STANDARD.md; keep entrypoints thin, package responsibilities explicit, and existing debt baseline-managed.
- **Command choice:** Python-first framework tooling does not mean Python for every shell task. Use shell-native tools such as `rg`, `sed`, `find`, `wc`, and `git` for normal inspection. Use Python for repo-native Python tools, Python tests, or structured parsing when a normal CLI is unavailable or less reliable.
- **Public/private boundary:** Keep repo-maintenance plans, private audits, ledgers, local indexes, credentials, logs, caches, and planning transcripts out of public framework docs/templates. Use private ignored paths such as `.codex/runs/` and `.localsetup-maint/` for maintenance state, and do not stage private/local paths.
- **Skill/context preservation:** When editing skill or context files, preserve task capability over brevity. Material reductions require a preservation inventory; large reductions are review triggers. Full rule lives in `ls-context`.

## Output contract (low token, always apply)

- Detect output capability: `markdown-rich`, `markdown-basic`, or `text-basic`.
- If capability is unknown, default to `markdown-basic`.
- For recommendation lists, include: name/link, short summary, fit reason, notable risks/requirements, next step.
- Use tables only when capability clearly supports readable tables.

## Agent orchestration and model budget

- Inventory and scouting: use `gpt-5.4-mini` for cheap repo/file inventory, low-risk search, and parallel subagent scouting.
- Critical review: use `gpt-5.5` at medium reasoning for security, release blockers, architecture, and high-risk review findings.
- Bounded coding: use `gpt-5.3-codex` for scoped implementation tasks with clear write ownership and tests.
- Credit freshness: Codex credit rates are volatile. Re-check the official Codex rate card at https://help.openai.com/en/articles/20001106-codex-rate-card before changing model guidance or making cost-sensitive routing decisions.
- If `.localsetup/AGENT_STATUS.md` exists, read it before repairs or installs. Otherwise run `localsetup health --json` for the latest Localsetup health status and next repair command.

## Capability skills and workflow packages index (load when task matches)

| Package | When to use |
|-------|--------------|
| ls-workflow-spec-clarify-reverse | User says "decision tree" or "reverse prompt"; editing .agent/queue/**, PRD |
| ls-workflow-umbrella-run | Queue/PRD in scope; named workflows; impact summary + confirmation |
| ls-workflow-queue-batch-implement | "Process PRDs", "run batch from PRD folder"; implement per spec, outcome |
| ls-agentq-transport | Ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; see AGENTIC_AGENT_Q_SCENARIOS.md |
| ls-mail-protocol-control | SMTP/IMAP; preencrypted_openpgp_armored for Agent Q strict mail |
| ls-public-repo-identity | Editing README*, CONTRIBUTING*; public identity |
| ls-framework-compliance | Framework modifications, PRDs, checklist/checkpoints |
| ls-safety-and-backup | Destructive ops, backups, temp files, firewall |
| ls-script-and-docs-quality | Generating scripts, markdown/docs |
| ls-communication-and-tools | Communication style, tool choice, MCP/context updates |
| ls-workflow-ops-tmux-session | Server/system commands, deployments, tmux, shared session, human-in-the-loop ops |
| ls-workflow-tmux-terminal-mode | Enable, disable, and status checks for tmux-default terminal mode |
| ls-automatic-versioning | Version bumps, release workflow, conventional commits, versioning docs |
| ls-github-publishing-workflow | Publishing to GitHub, public release prep, publishing checklist, repo readiness |
| ls-github-starredrepos | Manage a GitHub starred repositories archive named starredrepos; authenticated context checks, dry-run sync, repo scouting, metadata snapshots, and guarded publish workflows |
| ls-codex-heartbeat | Opt-in Codex heartbeat harness; use localsetup harness codex-heartbeat plan/init/enable/status/run/disable; normal install does not activate autonomous runs |
| ls-skill-creator | Create new capability skill from an existing doc/markdown/GitHub source; use workflow packages for named orchestration flows |
| ls-skill-importer | Import skills from URL or local path; discover, validate, screen, summarize; user picks which to import |
| ls-skill-discovery | Discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt |
| ls-task-skill-matcher | Match user tasks to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions |
| ls-backlog-and-reminders | Record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked |
| ls-humanizer | Humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing) |
| ls-test-runner | Write and run tests across languages and frameworks; TDD, coverage |
| ls-tdd-guide | TDD workflow, test generation, coverage analysis |
| ls-receiving-code-review | Use when receiving code review feedback; verify before implementing |
| ls-pr-reviewer | Automated GitHub PR code review with diff analysis, lint |
| ls-debug-pro | Systematic debugging methodology and language-specific debugging |
| ls-git-workflows | Advanced git (rebase, bisect, worktree, reflog) |
| ls-unfuck-my-git-state | Diagnose and recover broken Git state and worktree |
| ls-skill-vetter | Security-first skill vetting before installing external skills |
| ls-mcp-builder | Guide for creating high-quality MCP servers |
| ls-arbiter | Push decisions for async human review (Arbiter Zebu) |
| ls-ansible-skill | Ansible playbooks, server provisioning, config management, multi-host orchestration |
| ls-linux-service-triage | Diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps |
| ls-linux-patcher | Automated Linux patching and Docker container updates; multi-host server maintenance |
| ls-skill-normalizer | Normalize skills for spec compliance and platform-neutral wording; one skill or all |
| ls-skill-sandbox-tester | Test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until approved |
| ls-agentlens | Codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs |
| ls-context-index | SQLite-backed context index and vector-first search; use preflight/freshness before broad recursive reads |
| ls-framework-audit | Doc/link/skill matrix/version checks; output path required (`run_framework_audit.py --output`); before release |
| ls-markdown-reference-validator | Validate markdown local references/anchors from YAML-configured targets; emit scheduled-safe audit report for docs/skills/global Kilo surfaces |
| ls-system-info | Capture server baseline, host layout and specs; CPU, memory, disk, uptime |
| ls-cron-orchestrator | Manage cron from manifest; triggers, sequenced tasks, on-boot delay; create/remove/reorder/install |
| ls-cloudflare-dns | Manage Cloudflare DNS records and zone DNS settings through direct Cloudflare v4 REST API tooling |
| ls-npm-management | Manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows |
| ls-keepass-secrets | KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate |
| ls-docs-organization | Docs organization router; classify docs, choose folder slugs, keep docs indexes in sync |
| ls-scrapling | Host-first Scrapling integration; install/upgrade via pipx, run adaptive single-URL extractions. Default web scraping skill. |
| ls-omniroute | Ambiguous-task/preflight router only for unclassified triage, env/API-key/access preflight, and non-mutating onboarding; route classified read-only discovery to ls-omniroute-proxy, mutation to ls-omniroute-admin-automation, and source/coverage maintenance to ls-omniroute-update |
| ls-omniroute-proxy | All read-only OmniRoute model/provider, context, observability, integration, client and endpoint discovery, plus sanitized model observations |
| ls-omniroute-admin-automation | All OmniRoute writes, imports, purges, services, settings, providers, keys, integrations, backup/restore, and rollback-safe reconciliation |
| ls-omniroute-update | OmniRoute update reporting for upstream skill discovery, Localsetup coverage comparison, provenance metadata, and report-first maintenance planning |
| ls-kilo-boss-orchestrator | Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates |
| ls-kilo-visual-output | Kilo CLI visual output organization guide with structured response patterns |
| ls-typescript-code-quality | TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code |

## Framework docs index

- ls/docs/AGENTIC_DESIGN_INDEX.md  - Index of agentic design docs
- ls/docs/WORKFLOW_REGISTRY.md  - Named workflows, when to use, impact review
- ls/docs/WORKFLOW_QUICK_REF.md  - Workflow IDs, package names, aliases, primary docs
- ls/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md  - PRD/spec format, outcome template
- ls/docs/DECISION_TREE_WORKFLOW.md  - Decision tree (one Q per turn, A-D, preferred + rationale)
- ls/docs/INPUT_HARDENING_STANDARD.md  - Mandatory hostile-input handling, sanitization, actionable error policy
- ls/docs/TOOLING_POLICY.md  - Python-first tooling language and dependency policy
- ls/docs/PYTHON_ARCHITECTURE_STANDARD.md  - Python environment and package architecture policy

## Task-to-skill matching (default)

- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or when user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `ls/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `ls-task-skill-matcher` and `ls/docs/TASK_SKILL_MATCHING.md`.

## Key files (paths relative to ls/)

- lib/data_paths.sh  - Path resolution
- lib/json_formatter.sh  - JSON formatting
- tools/verify_rules  - Rule/checkpoint verification
- localsetup verify --level filesystem  - Verify installed adapters and managed packages
- discovery/core/os_detector.py  - OS detection

## Quick commands (run from repo root)

```bash
localsetup verify --tools kilo
localsetup context --markdown
./ls/discovery/discover
localsetup doctor
```

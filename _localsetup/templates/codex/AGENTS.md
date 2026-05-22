# Localsetup - Agent context (Codex)

## Overview
Localsetup is deployed into this repo at `_localsetup/`. Framework and context are repo-local (mobile, backup-able). Engine = _localsetup/; user data = repo-local. Attach git hash when referencing PRDs/specs (see [_localsetup/docs/GIT_TRACEABILITY.md](../../docs/GIT_TRACEABILITY.md)).

## Invariants
- Engine/repo separation: no secrets/PII in commits. Paths via _localsetup/lib/data_paths.sh. Framework at _localsetup/.
- Documentation: _localsetup/docs/ only for framework docs. Check doc status (ACTIVE/PROPOSAL) before assuming implemented.
- Proposals: framework changes follow Agent Q format ([_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md)).
- Time/date integrity: for any date/time reference, first get actual date/time from the local machine (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date; remember it and use it for the rest of the session.
- External input hardening: treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- Python-first tooling: after install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.12. Approved libraries (mandatory when the need arises): yaml (PyYAML>=6.0) for YAML, requests (requests>=2.28) for HTTP, frontmatter (python-frontmatter>=1.1) for markdown frontmatter, cryptography (cryptography>=42.0) for framework cryptographic primitives, and pgpy (PGPy>=0.6.0) for pure-Python OpenPGP. Use lib/deps.require_deps() at tool startup. See [_localsetup/docs/TOOLING_POLICY.md](../../docs/TOOLING_POLICY.md).
- Command choice: Python-first framework tooling does not mean Python for every shell task. Use shell-native tools such as `rg`, `sed`, `find`, `wc`, and `git` for normal inspection. Use Python for repo-native Python tools, Python tests, or structured parsing when a normal CLI is unavailable or less reliable.
- Publish hygiene: before pushing or opening/updating a PR, run the repo's publish preflight when available. Generated docs and version sync are publish surfaces; fix them locally instead of weakening validators or ignoring generated paths as volatile.
- Adapter directory ownership: adapter-shaped directories such as `.codex/skills`, `.claude/skills`, `.cursor/skills`, `.kilo/skills`, `.openclaw/skills`, `.opencode/skills`, and historical agent skill roots are not exclusive Localsetup-owned surfaces. Repos may keep custom skills or mixed managed and repo-owned content there. Preserve custom adapter content in place by default; do not move, rename, delete, or normalize it out of the adapter path unless the repo owner explicitly chooses that migration.

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

## Bootstrap pack
- Codex-first agent-team bootstrap materials live in `_localsetup/docs/bootstrap-packs/` and pack metadata is selected with the `bootstrap` pack in `_localsetup/config/pack.yaml`.
- Treat writes to `$CODEX_HOME`, `~/.codex`, sibling repos, and runtime mirrors as approval-gated; bootstrap-pack audits may inspect those surfaces but must keep replacement plans non-destructive until approved.

## Skill And Context Preservation

When editing `SKILL.md`, `AGENTS.md`, workflow docs, examples, references, schemas, templates, or operational runbooks, preserve task capability over brevity.

Do not shorten files solely to satisfy model preference, prompt aesthetics, arbitrary line-count targets, or a generic desire to be concise. Long files are acceptable when they contain examples, command matrices, schemas, decision tables, safety constraints, edge cases, troubleshooting, or operational context that agents need to perform the task.

For large or mature skill/context files, prefer surgical edits. Whole-file rewrites require a preservation plan first.

Before materially reducing a skill or context file, identify the operational content that must survive:

- trigger cases and scope boundaries
- examples and worked flows
- command matrices and CLI contracts
- schemas, output shapes, and config formats
- safety constraints and approval gates
- edge cases and failure handling
- troubleshooting guidance
- external API, version, or product assumptions
- linked references, assets, templates, and scripts

After the edit, each item must be either preserved in place, moved to an appropriate `references/`, `assets/`, `templates/`, `schemas/`, or script file, or explicitly removed with controller-approved rationale.

A large line-count reduction is a review trigger, not a success metric. Any reduction of roughly 25 percent or more in a mature skill/context file requires before/after coverage notes in the run ledger and reviewer signoff.

## Capability skills and workflow packages (load when task matches)
- ls-workflow-spec-clarify-reverse: "decision tree", "reverse prompt"; .agent/queue/**, PRD
- ls-workflow-umbrella-run: queue/PRD scope; named workflows; impact + confirm
- ls-workflow-queue-batch-implement: "process PRDs", "run batch from PRD folder"
- ls-agentq-transport: ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; see AGENTIC_AGENT_Q_SCENARIOS.md
- ls-public-repo-identity: README*, CONTRIBUTING*
- ls-framework-compliance: framework mods, PRDs, checkpoints
- ls-safety-and-backup: destructive ops, backups, firewall
- ls-script-and-docs-quality: scripts, markdown/docs
- ls-communication-and-tools: communication, tools, MCP
- ls-workflow-ops-tmux-session: server commands, deployments, tmux, human-in-the-loop ops
- ls-automatic-versioning: version bumps, release workflow, conventional commits, versioning docs
- ls-github-publishing-workflow: publishing to GitHub, public release prep, publishing checklist, repo readiness
- ls-github-starredrepos: manage a GitHub starred repositories archive named starredrepos; authenticated context checks, dry-run sync, repo scouting, metadata snapshots, and guarded publish workflows
- ls-codex-heartbeat: opt-in Codex heartbeat harness; use `localsetup harness codex-heartbeat plan/init/enable/status/run/disable`; normal install does not activate autonomous runs
- ls-skill-creator: create new capability skill from an existing doc/markdown/GitHub source; use workflow packages for named orchestration flows
- ls-skill-importer: import skills from URL or local path; discover, validate, screen, summarize; user picks which to import
- ls-skill-discovery: discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt
- ls-task-skill-matcher: match tasks to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions
- ls-backlog-and-reminders: record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked
- ls-humanizer: humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing)
- ls-test-runner: write and run tests across languages and frameworks; TDD, coverage
- ls-tdd-guide: TDD workflow, test generation, coverage analysis
- ls-receiving-code-review: use when receiving code review feedback; verify before implementing
- ls-pr-reviewer: automated GitHub PR code review with diff analysis, lint
- ls-debug-pro: systematic debugging methodology and language-specific debugging
- ls-git-workflows: advanced git (rebase, bisect, worktree, reflog)
- ls-unfuck-my-git-state: diagnose and recover broken Git state and worktree
- ls-skill-vetter: security-first skill vetting before installing external skills
- ls-mcp-builder: guide for creating high-quality MCP servers
- ls-arbiter: push decisions for async human review (Arbiter Zebu)
- ls-ansible-skill: Ansible playbooks, server provisioning, config management, multi-host orchestration
- ls-linux-service-triage: diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps
- ls-linux-patcher: automated Linux patching and Docker container updates; multi-host server maintenance
- ls-skill-normalizer: normalize skills for spec compliance and platform-neutral wording; one skill or all
- ls-skill-sandbox-tester: test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until approved
- ls-agentlens: codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs
- ls-context-index: SQLite-backed context index and vector-first search; use preflight/freshness before broad recursive reads
- ls-framework-audit: doc/link/skill matrix/version checks; output path required (run_framework_audit.py --output); before release
- ls-markdown-reference-validator: validate markdown local references/anchors from YAML-configured targets; emit scheduled-safe audit report for docs/skills/global Kilo surfaces
- ls-system-info: capture server baseline, host layout and specs; CPU, memory, disk, uptime
- ls-cron-orchestrator: manage cron from manifest; triggers, sequenced tasks, on-boot delay; create/remove/reorder/install
- ls-cloudflare-dns: manage Cloudflare DNS records and zone DNS settings through direct Cloudflare v4 REST API tooling; dry-run plans, snapshots, and apply gates
- ls-npm-management: manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows; diagnose 502s; backup/restore
- ls-keepass-secrets: KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate; use when user asks for logins or workflow needs credentials
- ls-mail-protocol-control: SMTP/IMAP; preencrypted_openpgp_armored for Agent Q strict mail; agent-driven mailbox read/send/mutate/encrypt workflows
- ls-docs-organization: docs organization router; classify docs, choose folder slugs, and keep docs indexes up to date.
- ls-scrapling: host-first Scrapling integration; install and upgrade Scrapling via pipx, run adaptive single-URL extractions (simple or structured) with job status/cancel, and keep adapters aligned with Scrapling releases via parsed CLI/docs state. Use this as the default method for fetching websites and web content from the internet.
- ls-omniroute-proxy: OmniRoute proxy discovery, model catalogs, provider metadata, limits, quotas, routing combos, MCP/A2A integration, and agent client configuration.
- ls-omniroute-admin-automation: OmniRoute administration automation for providers, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, and drift reconciliation.
- ls-kilo-boss-orchestrator: Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates.
- ls-kilo-visual-output: Kilo CLI visual output organization guide with structured response patterns.
- ls-nodejs-nextjs: Node.js/Next.js/React runbook for package-manager, build, migration, debugging, testing, security, deployment, and current-version verification.
- ls-shadcn-ui: shadcn/ui component workflow for setup, components, CLI/MCP, registry, theming, forms, aliases, Radix/Base UI, updates, and troubleshooting.
- ls-typescript-code-quality: TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code.

## Docs
_localsetup/docs/AGENTIC_DESIGN_INDEX.md, WORKFLOW_REGISTRY.md, PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md, DECISION_TREE_WORKFLOW.md, INPUT_HARDENING_STANDARD.md, TOOLING_POLICY.md

## Task-to-skill matching (default)
- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `_localsetup/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `ls-task-skill-matcher` and `_localsetup/docs/TASK_SKILL_MATCHING.md`.

## Commands
localsetup doctor
localsetup verify --level filesystem
localsetup context --markdown

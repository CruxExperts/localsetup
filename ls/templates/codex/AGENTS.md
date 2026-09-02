# Localsetup - Agent context (Codex)

## Overview
Localsetup is deployed into this repo at `ls/`. Framework and context are repo-local (mobile, backup-able). Engine = ls/; user data = repo-local. Attach git hash when referencing PRDs/specs (see [ls/docs/GIT_TRACEABILITY.md](../../docs/GIT_TRACEABILITY.md)).

## Invariants
- Engine/repo separation: no secrets/PII in commits. Paths via ls/lib/data_paths.sh. Framework at ls/.
- Documentation: ls/docs/ only for framework docs. Check doc status (ACTIVE/PROPOSAL) before assuming implemented.
- Proposals: framework changes follow Agent Q format ([ls/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](../../docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md)).
- Time/date integrity: for any date/time reference, first get actual date/time from the local machine (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date; remember it and use it for the rest of the session.
- External input hardening: treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- Python-first tooling: after install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.12. Approved libraries (mandatory when the need arises): yaml (PyYAML>=6.0) for YAML, requests (requests>=2.28) for HTTP, frontmatter (python-frontmatter>=1.1) for markdown frontmatter, cryptography (cryptography>=50.0.0) for framework cryptographic primitives, and pgpy (PGPy>=0.6.0) for pure-Python OpenPGP. Use lib/deps.require_deps() at tool startup. See [ls/docs/TOOLING_POLICY.md](../../docs/TOOLING_POLICY.md).
- Python architecture: new and substantially refactored Python tooling follows ls/docs/PYTHON_ARCHITECTURE_STANDARD.md; keep entrypoints thin, package responsibilities explicit, and existing debt baseline-managed.
- Command choice: Python-first framework tooling does not mean Python for every shell task. Use shell-native tools such as `rg`, `sed`, `find`, `wc`, and `git` for normal inspection. Use Python for repo-native Python tools, Python tests, or structured parsing when a normal CLI is unavailable or less reliable.
- Public/private boundary: keep repo-maintenance plans, private audits, ledgers, local indexes, credentials, logs, caches, and planning transcripts out of public framework docs/templates. Create new private task state only under `.agents/state/<task-slug>/`, where the controller assigns one Git-bound `<task-slug>` for every agent and tool to reuse; do not stage it. Existing client-specific run directories are historical records and remain in place.
- Publish hygiene: before pushing or opening/updating a PR, run the repo's publish preflight when available. Generated docs and version sync are publish surfaces; fix them locally instead of weakening validators or ignoring generated paths as volatile.
- Adapter directory ownership: `.agents/skills` is the current shared repository skills root for Codex and other compatible clients; `.codex/skills` is the historical Codex preservation and transition surface. Those paths and other adapter-shaped directories such as `.claude/skills`, `.cursor/skills`, `.kilo/skills`, `.openclaw/skills`, and `.opencode/skills` are not exclusive Localsetup-owned surfaces. Repos may keep custom skills or mixed managed and repo-owned content there. Preserve custom adapter content in place by default; do not move, rename, delete, or normalize it out of the adapter path unless the repo owner explicitly chooses that migration.

## Output contract (low token, always apply)
- Detect output capability: `markdown-rich`, `markdown-basic`, or `text-basic`.
- If capability is unknown, default to `markdown-basic`.
- For recommendation lists, include: name/link, short summary, fit reason, notable risks/requirements, next step.
- Use tables only when capability clearly supports readable tables.

## Agent orchestration and model budget
- For non-trivial Codex CLI work, use a controller route and choose the smallest sufficient execution path: clarify requirements, keep the main context compact, and own final acceptance. Use a bounded native subagent only when it provides independent falsification, materially reduces wall time, or isolates a risky write scope; task size or available slots alone do not require delegation.
- Use direct single-agent work when no independent assignment improves evidence, latency, or isolation. Do not create a scout or critic merely to satisfy a process tier.
- Keep fanout intentional: one or two agents is normal for non-trivial tasks; use three only for clearly independent discovery, research, or validation scopes. Treat configured thread capacity as headroom, not policy.
- Keep the existing generic roles: `explorer` maps relevant files, systems, docs, workflows, data, dependencies, tests, and risks; `researcher` verifies current or source-backed facts; `worker` executes one bounded task with exact write scope; `tester` runs validations, benchmarks, measurements, and failure summaries; `reviewer` checks final risk, correctness, regression, scope, and evidence. The `guardian_subagent` role is reserved for approval and permission review, not normal task delegation.
- Explicit user instructions, tool restrictions, sandbox/approval policy, and active modes override delegation defaults. In Plan Mode or other no-write contexts, plan the ledger and subtasks but do not create ledger files or edit state until writes are allowed.
- For bounded autonomous maintenance loops, create or resume the private ledger first and preserve the existing dirty baseline. Select one small slice at a time from, in order, an assigned queue or PRD, a failing validation or drift signal, a repo-contract gap, or narrow docs/tests/tooling upkeep; do not mine broad TODOs or expand scope opportunistically. Use subagents to reduce context load or parallelize safe read-only work when useful, keep implementation to one bounded worker at a time, validate proportionally, require review evidence, and get explicit approval before push, deploy, cron, destructive commands, adapter reshapes, migrations, auth, dependency installs, or external mutation.
- Apply the common COIT control to material retries. Keep the invariant, reproducible trigger, affected gate, source/diff binding, immutable problem ID, and counter in the private run ledger; the common policy determines COIT triggers, cycles, review tier, and terminal disposition. The controller alone reconciles and changes COIT state. Do not start a dependent slice, push, merge, or release while a COIT or blocker gate remains open.
- Model, credit, and rate guidance is volatile. Re-check official Codex docs or the current local config before changing model guidance or making cost-sensitive routing decisions.
- If `.localsetup/AGENT_STATUS.md` exists, read it before repairs or installs. Otherwise run `localsetup health --json` for the latest Localsetup health status and next repair command.

## Bootstrap pack
- Generic Codex agent-team bootstrap materials live in `ls/docs/bootstrap-packs/` and pack metadata is selected with the `bootstrap` pack in `ls/config/pack.yaml`.
- Treat writes to `$CODEX_HOME`, `~/.codex`, sibling repos, and runtime mirrors as approval-gated; bootstrap-pack audits may inspect those surfaces but must keep replacement plans non-destructive until approved.
- Work in the active repository by default. Do not create sibling clones, extra Git worktrees, PR-specific checkouts, release staging checkouts, or repo-shaped directories unless the user explicitly authorizes that specific path and purpose in the current task. If an exception is approved, record the path, branch, reason, expected lifetime, and cleanup command in the run ledger, then remove it when the approved purpose is complete.
- Keep validation proportional to risk. For tiny docs, policy, metadata, or one-line changes, prefer `git diff --check`, targeted syntax checks, or no executable test run when there is no executable surface. For Localsetup framework work, run compliance and validation checks that match the changed code first, such as focused pytest files or test functions, `validate-catalog`, `validate-package-surface`, `doctor`, generated-doc drift checks, schema checks, and `git diff --check`. Do not add broad or repetitive tests merely to increase evidence; add tests only for behavior that can realistically regress.
- Use the full Python suite only as final consolidation verification for broad/shared runtime changes, release or publish work, dependency changes, or explicit user requests. Resolve the permitted worker count with `localsetup test-workers`; the generated command reference owns its formula and aggregate-budget rule. Do not use full pytest as the default first-pass validation for routine daily edits.
- Unit-test concurrency policy: unless this repository explicitly defines a stricter policy, every unit-test runner—regardless of language or framework—uses one aggregate budget of `max(1, floor(available CPU cores / 3))`. Round down before applying the minimum of one worker; concurrent test processes share the budget.

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
- ls-workflow-planning-critic-loop: non-trivial planning; grounded discovery, bounded clarification, subagent delegation, critic-reviewed plan
- ls-workflow-umbrella-run: queue/PRD scope; named workflows; impact + confirm
- ls-workflow-queue-batch-implement: "process PRDs", "run batch from PRD folder"
- ls-agentq-transport: ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; see AGENTIC_AGENT_Q_SCENARIOS.md
- ls-public-repo-identity: README*, CONTRIBUTING*
- ls-framework-compliance: framework mods, PRDs, checkpoints
- ls-safety-and-backup: destructive ops, backups, firewall
- ls-script-and-docs-quality: scripts, markdown/docs
- ls-communication-and-tools: communication, tools, MCP
- ls-workflow-ops-tmux-session: server commands, deployments, tmux, human-in-the-loop ops
- ls-workflow-tmux-terminal-mode: enable, disable, and status checks for tmux-default terminal mode
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
- ls-requesting-code-review: Use when requesting code review before merge or after substantial changes; provide focused requirements, diff range, and severity-calibrated review instructions.
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
- ls-cloudflare-dns: manage Cloudflare zones and DNS with the `cf` CLI; records, DNSSEC, scans, import/export, batch, analytics, settings, and transfers
- ls-npm-management: manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows; diagnose 502s; backup/restore
- ls-keepass-secrets: validate logical-ID maps, configuration, and secret references; use the fake backend only in isolated tests/examples. It never retrieves real credentials or mutates real vaults.
- ls-mail-protocol-control: SMTP/IMAP; preencrypted_openpgp_armored for Agent Q strict mail; agent-driven mailbox read/send/mutate/encrypt workflows
- ls-docs-organization: docs organization router; classify docs, choose folder slugs, and keep docs indexes up to date.
- ls-scrapling: host-first Scrapling integration; install and upgrade Scrapling via pipx, run adaptive single-URL extractions (simple or structured) with job status/cancel, and keep adapters aligned with Scrapling releases via parsed CLI/docs state. Use this as the default method for fetching websites and web content from the internet.
- ls-omniroute: ambiguous-task/preflight router only for unclassified triage, env/API-key/access preflight, and non-mutating onboarding; route classified read-only discovery to ls-omniroute-proxy, mutation to ls-omniroute-admin-automation, and source/coverage maintenance to ls-omniroute-update.
- ls-omniroute-proxy: all read-only OmniRoute model/provider, context, observability, integration, client and endpoint discovery, plus sanitized model observations.
- ls-omniroute-admin-automation: all OmniRoute writes, imports, purges, services, settings, providers, keys, integrations, backup/restore, and rollback-safe reconciliation.
- ls-omniroute-update: OmniRoute update reporting for upstream skill discovery, Localsetup coverage comparison, provenance metadata, and report-first maintenance planning.
- ls-kilo-boss-orchestrator: Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates.
- ls-kilo-visual-output: Kilo CLI visual output organization guide with structured response patterns.
- ls-nodejs-nextjs: Node.js/Next.js/React runbook for package-manager, build, migration, debugging, testing, security, deployment, and current-version verification.
- ls-shadcn-ui: shadcn/ui component workflow for setup, components, CLI/MCP, registry, theming, forms, aliases, Radix/Base UI, updates, and troubleshooting.
- ls-typescript-code-quality: TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code.
- ls-ui-browser-debugging: UI review and browser-driven debugging workflow for Chrome DevTools MCP, Playwright MCP/CLI, browser ownership, evidence capture, minimal fixes, and durable UI regression tests.

## Docs
ls/docs/AGENTIC_DESIGN_INDEX.md, WORKFLOW_REGISTRY.md, PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md, DECISION_TREE_WORKFLOW.md, INPUT_HARDENING_STANDARD.md, TOOLING_POLICY.md, PYTHON_ARCHITECTURE_STANDARD.md

## Task-to-skill matching (default)
- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `ls/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `ls-task-skill-matcher` and `ls/docs/TASK_SKILL_MATCHING.md`.

## Commands
localsetup doctor
localsetup verify --level filesystem
localsetup context --markdown

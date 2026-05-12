# Localsetup v3 - Context and skills index

| Asset | Description | When applied |
|-------|-------------|--------------|
| ls-context.mdc | Master rule: overview, invariants, skills index, docs index | Always |
| ls-workflow-spec-clarify-reverse | Decision tree / reverse prompt; one Q per turn, 4 options A-D | User says "decision tree" or "reverse prompt"; editing .agent/queue/**, PRD |
| ls-workflow-umbrella-run | Umbrella/queue; named workflows; impact summary + confirmation | Queue/PRD in scope |
| ls-workflow-queue-batch-implement | Process PRDs; implement per spec; status; outcome | "Process PRDs", "run batch from PRD folder" |
| ls-public-repo-identity | Public repo identity; use local-identity for PII | Editing README*, CONTRIBUTING* |
| ls-framework-compliance | Pre-task workflow, checkpoints, document maintenance | Framework mods, PRDs, checklist tasks |
| ls-safety-and-backup | Security, backup, temp files, firewall | Destructive ops, system config, backups |
| ls-script-and-docs-quality | Markdown/encoding, script quality, file/docs discipline | Generating scripts, editing markdown/docs |
| ls-communication-and-tools | Communication, tool selection, periodic updates | Communication style, tools, MCP |
| ls-workflow-ops-tmux-session | Shared tmux session; sudo discovery and single-prompt gate (join session, trigger, batch until timeout); agent captures output; human can attach/sudo | Server commands, deployments, tmux, human-in-the-loop ops |
| ls-automatic-versioning | Automatic semantic versioning from conventional commits; VERSION, sync to READMEs/docs | Version bumps, release workflow, conventional commits, versioning docs |
| ls-github-publishing-workflow | Publishing checklist, doc structure, licensing, scrub for PII/secrets | Publishing to GitHub, public release prep, publishing checklist, repo readiness |
| ls-github-starredrepos | GitHub starred repositories archive named starredrepos | Authenticated context checks, dry-run sync, repo scouting, metadata snapshots, and guarded publish workflows |
| ls-skill-creator | Create framework capability skill from existing doc/markdown/GitHub source | Create new skill; use workflow packages for named orchestration flows; adapt doc or skill into framework |
| ls-skill-importer | Import skills from URL (e.g. GitHub) or local path; discover, validate, screen, summarize; user picks which to import | Import skills from URL/path, screen external skills, add skills from repo |
| ls-skill-discovery | Discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt | Creating/importing skill; find similar public skills; PUBLIC_SKILL_REGISTRY.urls, PUBLIC_SKILL_INDEX.yaml |
| ls-task-skill-matcher | Match task intent to installed skills; top-3 ranking, confirm/auto-pick flow, batch parcel options, and complementary public-skill suggestions | User asks "what skill should I use?", "pick the best", or task-to-skill match is unclear |
| ls-backlog-and-reminders | Record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked | "Add to backlog", "remind me", "what's due?", "show my backlog", "start my session" |
| ls-humanizer | Humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing) | Editing or reviewing text to sound more natural and human-written |
| ls-test-runner | Write and run tests across languages and frameworks (Vitest, Jest, pytest, Playwright) | Generating or running tests, TDD, coverage |
| ls-tdd-guide | TDD workflow, test generation, coverage analysis, red-green-refactor | Generate tests, analyze coverage, TDD cycles |
| ls-receiving-code-review | Use when receiving code review feedback; verify before implementing | After code review; implementing or responding to feedback |
| ls-pr-reviewer | Automated GitHub PR code review with diff analysis, lint | Reviewing pull requests before merge |
| ls-debug-pro | Systematic debugging methodology and language-specific debugging commands | Debugging failures, reproducing bugs, regression tests |
| ls-git-workflows | Advanced git (rebase, bisect, worktree, reflog, conflicts) | Rebase, bisect, worktrees, recovery |
| ls-unfuck-my-git-state | Diagnose and recover broken Git state and worktree | Broken Git state, worktree errors, recovery |
| ls-skill-vetter | Security-first skill vetting before installing external skills | Before installing any skill from external source |
| ls-mcp-builder | Guide for creating high-quality MCP servers (Python, TypeScript) | Building MCP servers, integrating external APIs |
| ls-arbiter | Push decisions to Arbiter Zebu for async human review | Plan review, architectural decisions, human approval |
| ls-ansible-skill | Ansible infra automation; server provisioning, config management, deployment | Ansible playbooks, multi-host orchestration, server config |
| ls-linux-service-triage | Diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS) | Failing or misconfigured server apps, service triage |
| ls-linux-patcher | Automated Linux patching and Docker container updates | Server maintenance, security updates, multi-host patching |
| ls-skill-normalizer | Phase 1: documents (platform choice when platform-specific); Phase 2: tooling to framework standard | Normalize one or all skills; batch review imported or dropped-in skills |
| ls-skill-sandbox-tester | Test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until user approves | Validate skill after import, test skill in sandbox, ensure skill runs before production |
| ls-agentlens | Codebase navigation with agentlens hierarchy (INDEX.md, modules, outline, memory) | Explore codebases, find modules/symbols, TODOs/warnings; large repos |
| ls-framework-audit | Doc/link/skill matrix/version checks; output path required (`run_framework_audit.py --output`) | User says "run audit", "run framework audit", or before release |
| ls-markdown-reference-validator | Validate markdown local references/anchors from YAML-configured targets and emit audit report | Validating docs/skills/global Kilo references; periodic archive integrity checks |
| ls-system-info | Quick system diagnostics: CPU, memory, disk, uptime | Capture server baseline, host layout and specs for further operations |
| ls-cron-orchestrator | Manage cron from manifest: triggers, sequenced tasks, on-boot delay | Create/remove/reorder cron tasks; install crontab fragment |
| ls-cloudflare-dns | Manage Cloudflare DNS records and zone DNS settings through direct Cloudflare v4 REST API tooling | DNS record changes; DNS settings; dry-run plans; snapshots |
| ls-npm-management | Manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker service deployments with NPM routing | Create/modify/remove NPM proxy hosts; diagnose 502s; backup/restore; Docker + NPM deploy workflows |
| ls-keepass-secrets | KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate; never embed in repo | User asks for logins, workflow needs credentials, or bulk account creation |
| ls-mail-protocol-control | Manage delegated SMTP/IMAP accounts with attachment-first MIME handling, chunked attachment retrieval, and full-envelope encryption/decryption tools | Agent-driven mailbox read/send/mutate/encrypt workflows; preencrypted_openpgp_armored for Agent Q strict mail ship |
| ls-agentq-transport | Agent Q bidirectional transport: file_drop ship/ingest, mail pull/ship (strict gpg), registry, queue-pending, archive-prune | Ship/ingest sealed PRD manifests between agents; see AGENTIC_AGENT_Q_SCENARIOS.md |
| ls-docs-organization | Docs organization router for repo docs; classify doc work, choose folder slugs, and keep docs indexes in sync | Creating, moving, or significantly updating docs; deciding placement and index updates |
| ls-omniroute-proxy | OmniRoute proxy discovery, model catalogs, provider metadata, limits, quotas, routing combos, MCP/A2A integration, and agent client configuration | OmniRoute catalogs, provider limits, routing combos, or configuring agents to use OmniRoute |
| ls-omniroute-admin-automation | OmniRoute administration automation for providers, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, and drift reconciliation | OmniRoute admin changes, reconciliation, backup/restore, key and policy management |
| ls-kilo-boss-orchestrator | Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates | Multi-agent autonomous loops requiring planning, delegation, verification, and discrepancy adjudication |
| ls-kilo-visual-output | Kilo CLI visual output organization guide with structured response patterns | Kilo output formatting, options, rationale blocks, and execution summaries |
| ls-nodejs-nextjs | Node.js/Next.js/React runbook | Package-manager, build, migration, debugging, testing, security, deployment, and current-version verification |
| ls-shadcn-ui | shadcn/ui component workflow | Setup, components, CLI/MCP, registry, theming, forms, aliases, Radix/Base UI, updates, and troubleshooting |
| ls-scrapling | Host-first Scrapling integration; install/upgrade via pipx, run single-URL extractions with adaptive fetch modes and job tracking, and keep adapters current via parsed CLI/docs state | **Default** web scraping and website fetching skill; use for most tasks that need content from public web pages |
| ls-typescript-code-quality | TypeScript code quality guide | TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code |

Framework docs: _localsetup/docs/ (AGENTIC_DESIGN_INDEX.md, WORKFLOW_REGISTRY.md, PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).

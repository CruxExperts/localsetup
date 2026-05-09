# Localsetup v3 Framework

**Version:** 3.0.1<br>
**Last updated:** 2026-05-07

This directory is the engine of Localsetup v3: a universal, cross-platform agentic workflow framework for DevOps, local and remote servers, network configuration, and any workflow that benefits from AI agent assistance on your chosen platform (see [Platform registry](docs/PLATFORM_REGISTRY.md) for the canonical list: Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, Kilo, and OpenCode). For first-time setup and overview, see the [root README](../README.md). Deployed into your repo, the framework source and context live inside the repo so the setup is mobile and reviewable. Runtime skill copies live in the managed home library and can be recreated from repo source.

The framework is for anyone who wants to execute tasks with agents: it provides a convenient, contained place for workflows and skills. It is **lightweight**, **does not interfere with existing projects**, and works for a **wide variety of tasks**; it is **compatible with all agentic design patterns** and **platform-independent** -the same skills and workflows run on any supported host.

The emphasis is on **transparency**, **security**, and **high-quality operations** with **traceability**. Use the built-in skills as-is, **create new skills** from your workflow or from existing docs (skill-creator), or **import external skills** from a URL (e.g. GitHub) or local path -the framework discovers and validates them, runs a heuristic security screen, and summarizes each so you choose which to import (skill-importer). Skills follow the [Agent Skills](https://agentskills.io/specification) specification and are **interchangeable**: use skills from ecosystems like [Anthropic's skills](https://github.com/anthropics/skills) in this framework, and use this framework's skills in any spec-compliant host. Agents load context and skills by task (decision trees, PRD batches, safety, tmux, versioning, publishing, and more), with human-in-the-loop where needed and git-coupled references for PRDs, specs, and outcomes.

<p align="center">
  <img src="../assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, resolved config, managed home library, adapters, and rollback metadata" width="960">
</p>

---

## Table of contents

- [Overview](#overview)
- [Installation](#installation)
- [Requirements](#requirements)
- [Project structure](#project-structure)
- [Documentation](#documentation)
- [Skills](#skills)
- [Tools](#tools)
- [Libraries and configuration](#libraries-and-configuration)
- [Workflows](#workflows)
- [Verification and testing](#verification-and-testing)
- [Author and contact](#author-and-contact)
- [License and copyright](#license-and-copyright)
- [Contributing and license](#contributing-and-license)

---

## Overview

**Summary of features:** One-line Bash install for Linux, macOS, and WSL2; multi-platform deploy (cursor, claude-code, codex, openclaw, kilo, opencode); always-loaded context per platform; built-in skills (decision tree, PRD batch, safety, tmux, versioning, publishing, skill-creator, skill-importer, skill-discovery, agentlens, and more); duplicate/overlap/namespace checks when creating or importing; heuristic security screening on import; public skill registry and index with refresh and top-5 similar recommendations; versioning (VERSION, conventional commits, per-skill metadata.version); Python-first tools (localsetup_v3.py, verify_context, verify_rules, skill_importer_scan); docs under [docs/](docs/) and [AGENTIC_DESIGN_INDEX.md](docs/AGENTIC_DESIGN_INDEX.md).

Localsetup v3 provides:

- **One always-loaded context** per supported platform (canonical list: [docs/PLATFORM_REGISTRY.md](docs/PLATFORM_REGISTRY.md)) with invariants, skills index, and docs index.
- **Skills** (task-based instructions) that agents load when the task matches -e.g. decision tree, PRD batch, safety, tmux, versioning, publishing. Create new skills from workflows or docs (skill-creator); import external skills from a URL or path with validation and security screening (skill-importer). Skills are [Agent Skills](https://agentskills.io/specification)–compliant and interchangeable with other spec-compliant hosts.
- **Named workflows and quick reference**: decision tree, Agent Q queue, umbrella workflow, guarded/manual ops, tmux terminal mode, and more, all indexed with Workflow IDs, display names, and aliases in [docs/WORKFLOW_REGISTRY.md](docs/WORKFLOW_REGISTRY.md), with an agent-facing quick reference and composite pipelines in [docs/WORKFLOW_QUICK_REF.md](docs/WORKFLOW_QUICK_REF.md).
- **Bidirectional Agent Q + PRD integration**: PRD schema, queue pattern, and agent-to-agent protocol are wired together. See [docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) for PRD shape and outcome blocks, [docs/AGENTIC_AGENT_Q_PATTERN.md](docs/AGENTIC_AGENT_Q_PATTERN.md) for queue layout, and [docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) plus [docs/AGENTIC_AGENT_Q_SCENARIOS.md](docs/AGENTIC_AGENT_Q_SCENARIOS.md) for transport behavior.
- **Repo-local everything**: engine at `_localsetup/`, user/context data under the repo; [git traceability](docs/GIT_TRACEABILITY.md) for PRDs, specs, and outcomes so operations stay transparent and auditable.

After installation, the client repo contains `_localsetup/` (this framework plus docs), source skills in `_localsetup/skills/ls-*`, and managed adapter paths at repo root (for example `.codex/skills` or `.kilo/skills`) that point to the shared home library. Version displayed in READMEs and framework docs is kept in sync with the repo **VERSION** file by the automatic release workflow.

<p align="center">
  <img src="../assets/localsetup-v3-install-lifecycle.svg" alt="Localsetup v3 install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

---

## Installation

Installation is run from the **repository root** (parent of this `_localsetup/` directory), not from inside `_localsetup/`.

**Linux / macOS (Bash):**

```bash
# Interactive
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash

# Non-interactive (agents/CI)
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools cursor --yes
```

**Windows:** Localsetup v3 supports Windows through WSL2 only. Open WSL2, change to the repository path, and run the Bash installer there:

```bash
./install --directory . --tools cursor --yes
```

The root `install.ps1` file is a compatibility guidance stub. It prints WSL2 instructions and exits; native PowerShell installation and Git Bash delegation are intentionally not supported in v3. See [Multi-platform install](docs/MULTI_PLATFORM_INSTALL.md) for full details.

**Options:**

| Option | Description |
|--------|-------------|
| `--directory PATH` | Client repo root (default: `.`) |
| `--tools LIST` | Comma-separated: `cursor`, `claude-code`, `codex`, `openclaw`, `kilo`, `opencode` |
| `--yes` | Non-interactive; no prompts (required when using `--tools`) |
| `--global` | Accepted for v2 compatibility; v3 installs the managed home library by default |
| `--help` | Print usage and exit |

**Examples:**

```bash
# Cursor only, non-interactive
install --directory . --tools cursor --yes

# Cursor + Claude Code
install --tools cursor,claude-code --yes

# Interactive (prompt for directory and tools)
install
```

**What gets deployed:**

- **All platforms:** Framework at `_localsetup/` (tools, lib, docs, skills, templates).
- **Per-platform** context and skills paths: see [docs/PLATFORM_REGISTRY.md](docs/PLATFORM_REGISTRY.md) (single source of truth for supported platforms and paths).

See [Multi-platform install](docs/MULTI_PLATFORM_INSTALL.md) for details.

---

## Requirements

- **Linux/macOS/WSL2:** Bash for bootstrap and Python `>= 3.10` for v3 framework tooling.
- **Windows:** WSL2. Native PowerShell install is not supported; `install.ps1` is a guidance stub.
- **Git** (for install clone/update; optional for `verify_rules`).
- One or more platforms from the [platform registry](docs/PLATFORM_REGISTRY.md) (e.g. cursor, claude-code, codex, openclaw), selected via `--tools` / `-Tools`.
- **Recommended (Python tooling):** For full skill validation/discovery tooling, public skill index refresh, scrub, and Python client skills (including secure mail crypto flows), use Python `>= 3.10` with the packages in `_localsetup/requirements.txt` (PyYAML>=6.0, requests>=2.28, python-frontmatter>=1.1, cryptography>=42.0, PGPy>=0.6.0). Pass `--install-deps` to create/update the managed `.localsetup/venv`; avoid system-pip overrides such as `--break-system-packages`.

---

## Project structure

Paths below are relative to the **framework directory** (e.g. `_localsetup/` after install when the repo is cloned into `_localsetup/`).

```
_localsetup/
├── README.md                 # This file
├── config/
│   └── defaults/
│       └── system_config.yaml   # Default framework folder name, user data subdir
├── discovery/
│   └── core/
│       ├── os_detector.py       # OS detection (canonical)
│       ├── os_detector.sh       # Launcher (Bash)
│       └── os_detector.ps1      # Launcher (PowerShell)
├── docs/                        # Framework documentation (copied to _localsetup/docs/)
│   ├── AGENTIC_DESIGN_INDEX.md
│   ├── DECISION_TREE_WORKFLOW.md
│   ├── GIT_TRACEABILITY.md
│   ├── MULTI_PLATFORM_INSTALL.md
│   ├── PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md
│   ├── SKILLS_AND_RULES.md
│   └── WORKFLOW_REGISTRY.md
├── lib/
│   ├── data_paths.sh            # Path resolution (Bash)
│   ├── data_paths.ps1           # Path resolution (PowerShell)
│   └── json_formatter.sh        # JSON formatting helpers
├── skills/                      # Source of truth for ls-* skills
│   └── ls-*/
│       └── SKILL.md
├── templates/                   # Platform-specific context loaders used by install planning
│   ├── cursor/
│   ├── claude-code/
│   ├── codex/
│   ├── kilo/
│   ├── openclaw/
│   └── opencode/
├── tests/
│   ├── automated_test.sh        # Minimal sanity tests (Bash)
│   └── automated_test.ps1       # Minimal sanity tests (PowerShell)
└── tools/
    ├── agentq_transport_client/ # Agent Q bidirectional CLI (ship-file-drop, ingest-blob, mail-pull, strict gpg)
    ├── localsetup_v3.py         # Plan, install, verify, rollback, docs, package, migration
    ├── refresh_public_skill_index.py   # Refresh PUBLIC_SKILL_INDEX.yaml from registry URLs (requires PyYAML; see requirements.txt)
    ├── skill_index_scrub.py            # Audit index for dead URLs, stub descriptions, schema gaps; --fix fetches real descriptions upstream
    ├── tmux_terminal_mode              # Enable/disable/status tmux-default terminal mode (Bash wrapper)
    ├── tmux_terminal_mode.py           # Main script: ide profile or shell auto-attach + agent rule injection
    ├── verify_context           # Check Cursor context file (Bash; on Windows delegates to .ps1)
    ├── verify_context.ps1       # Same (PowerShell)
    ├── verify_rules             # Check git, data_paths, skills (Bash; on Windows delegates to .ps1)
    └── verify_rules.ps1         # Same (PowerShell)
```

---

## Documentation

All docs live under `docs/` and are copied to `_localsetup/docs/` on deploy so that paths like `_localsetup/docs/...` work in the client repo.

| Document | Description |
|----------|-------------|
| [README.md](docs/README.md) | Public docs index for fast navigation |
| [QUICKSTART.md](docs/QUICKSTART.md) | One-command install and first verification |
| [FEATURES.md](docs/FEATURES.md) | Expanded framework feature set |
| [SKILLS.md](docs/SKILLS.md) | Generated shipped skills catalog from `_localsetup/skills/*/SKILL.md` |
| [AGENTIC_DESIGN_INDEX.md](docs/AGENTIC_DESIGN_INDEX.md) | Index of agentic-design docs and quick reference |
| [WORKFLOW_REGISTRY.md](docs/WORKFLOW_REGISTRY.md) | Named workflows; when to use; impact review |
| [PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md](docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md) | PRD/spec format, outcome template, external confirmation |
| [DECISION_TREE_WORKFLOW.md](docs/DECISION_TREE_WORKFLOW.md) | Decision tree: one Q per turn, 4 options A–D, preferred + rationale |
| [GIT_TRACEABILITY.md](docs/GIT_TRACEABILITY.md) | Attach git hash when referencing PRDs, specs, outcomes |
| [SKILLS_AND_RULES.md](docs/SKILLS_AND_RULES.md) | How master rule and skills interact; when to load which skill |
| [MULTI_PLATFORM_INSTALL.md](docs/MULTI_PLATFORM_INSTALL.md) | Install for supported platforms |
| [PLATFORM_REGISTRY.md](docs/PLATFORM_REGISTRY.md) | **Canonical list of supported AI agent platforms**; paths; skill registration file list |
| [AGENT_SKILLS_COMPLIANCE.md](docs/AGENT_SKILLS_COMPLIANCE.md) | Agent Skills spec compliance; skill document versioning (metadata.version); maintained by repo maintainers |
| [SKILL_INTEROPERABILITY.md](docs/SKILL_INTEROPERABILITY.md) | Import external skills (e.g. Anthropic); export our skills; interchange with spec-compliant hosts |
| [SKILL_IMPORTING.md](docs/SKILL_IMPORTING.md) | Import from URL or path; discover, validate, screen, summarize; user selects which skills to import |
| [SKILL_DISCOVERY.md](docs/SKILL_DISCOVERY.md) | Public skill registries (PUBLIC_SKILL_REGISTRY.urls, PUBLIC_SKILL_INDEX.yaml); recommend similar when creating/importing |
| [TASK_SKILL_MATCHING.md](docs/TASK_SKILL_MATCHING.md) | Task-to-installed-skill matching flow: single vs batch, auto-pick/parcel, complementary public-skill suggestions |
| [INPUT_HARDENING_STANDARD.md](docs/INPUT_HARDENING_STANDARD.md) | Hostile-input baseline: sanitization, validation, actionable error handling, and no-silent-failure policy |
| [TOOLING_POLICY.md](docs/TOOLING_POLICY.md) | Python-first tooling scope, runtime target, and minimal dependency policy |
| [AGENTIC_AGENT_Q_SCENARIOS.md](docs/AGENTIC_AGENT_Q_SCENARIOS.md) | file_drop/mail scenarios: repos, agents, local/remote |
| [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) | Agent-to-agent PRD handoff (ACTIVE) |

---

## Skills

Skills are task-based instructions (SKILL.md with `name` and `description` frontmatter). Agents load the appropriate skill when the task matches. The source of truth is `_localsetup/skills/ls-*`; v3 install copies selected skills into the managed home library at `~/.local/share/agents/skills/localsetup` and attaches platform adapter paths such as `.codex/skills`, `.cursor/skills`, `.kilo/skills`, and `.opencode/skills` to that managed library.

| Skill | When to use |
|-------|--------------|
| `ls-decision-tree-workflow` | User says "decision tree", "reverse prompt"; editing `.agent/queue/**`, PRD |
| `ls-agentic-umbrella-queue` | Queue/PRD in scope; named workflows; impact summary + confirmation |
| `ls-agentic-prd-batch` | "Process PRDs", "run batch from PRD folder"; implement per spec, outcome |
| `ls-agentq-transport` | Ship/ingest sealed Agent Q blobs (file_drop/mail), registry, strict gpg; see AGENTIC_AGENT_Q_SCENARIOS.md |
| `ls-mail-protocol-control` | SMTP/IMAP with preencrypted_openpgp_armored for Agent Q strict mail ship |
| `ls-public-repo-identity` | Editing README*, CONTRIBUTING*; public identity |
| `ls-framework-compliance` | Framework modifications, PRDs, checklist/checkpoints |
| `ls-safety-and-backup` | Destructive ops, backups, temp files, firewall |
| `ls-script-and-docs-quality` | Generating scripts, markdown/docs |
| `ls-communication-and-tools` | Communication style, tool choice, MCP/context updates |
| `ls-tmux-shared-session-workflow` | Server/ops in tmux via tmux_ops (pick, probe, send, wait); sudo gate via probe; adaptive idle polling (`send --wait` or `wait --timeout N`); REMOTE_TMUX_HOST for remote/VMs; human-in-the-loop ops |
| `ls-automatic-versioning` | Version bumps, release workflow, conventional commits, versioning docs |
| `ls-github-publishing-workflow` | Publishing to GitHub, public release prep, publishing checklist, repo readiness |
| `ls-skill-creator` | Create new skill from workflow or existing doc/markdown/GitHub; capture workflow as framework skill |
| `ls-skill-importer` | Import skills from URL or local path; discover, validate, screen, summarize; user picks which to import |
| `ls-skill-discovery` | Discover public skills from registries; recommend top 5 similar when creating/importing; in-depth summary, use public, continue, or adapt |
| `ls-task-skill-matcher` | Match task intent to installed skills; recommend top matches; single-task confirm once; batch auto-pick/parcel flow; complementary public-skill suggestions |
| `ls-backlog-and-reminders` | Record deferred ideas, to-dos, reminders (optional due or "whenever"); show due/overdue on session start or when asked |
| `ls-humanizer` | Humanize text; remove AI-writing patterns and add natural voice (rules-based, Wikipedia Signs of AI writing) |
| `ls-test-runner` | Write and run tests across languages and frameworks; TDD, coverage |
| `ls-tdd-guide` | TDD workflow, test generation, coverage analysis |
| `ls-receiving-code-review` | Use when receiving code review feedback; verify before implementing |
| `ls-pr-reviewer` | Automated GitHub PR code review with diff analysis, lint |
| `ls-debug-pro` | Systematic debugging methodology and language-specific debugging |
| `ls-git-workflows` | Advanced git (rebase, bisect, worktree, reflog) |
| `ls-unfuck-my-git-state` | Diagnose and recover broken Git state and worktree |
| `ls-skill-vetter` | Security-first skill vetting before installing external skills |
| `ls-mcp-builder` | Guide for creating high-quality MCP servers |
| `ls-arbiter` | Push decisions for async human review (Arbiter Zebu) |
| `ls-ansible-skill` | Ansible playbooks, server provisioning, config management, multi-host orchestration |
| `ls-linux-service-triage` | Diagnose Linux service issues (logs, systemd, PM2, Nginx, DNS); failing or misconfigured server apps |
| `ls-linux-patcher` | Automated Linux patching and Docker container updates; multi-host server maintenance |
| `ls-skill-normalizer` | Normalize skills: Phase 1 (documents, platform choice when platform-specific); Phase 2 (tooling rewrite to framework standard). One skill or all. |
| `ls-skill-sandbox-tester` | Test skills in isolated sandbox; smoke check; on failure use debug-pro; no repo writes until user approves |
| `ls-agentlens` | Codebase navigation with agentlens hierarchy; explore projects, find modules/symbols, TODOs |
| `ls-framework-audit` | Doc/link/skill matrix/version checks; output path required (`run_framework_audit.py --output`); before release |
| `ls-markdown-reference-validator` | Validate markdown local references and anchors across configured global+repo paths; scheduled-safe report generator with YAML sidecar config |
| `ls-cloudflare-dns` | Manage Cloudflare DNS records (list, create, modify, delete) and zone surveys via flarectl |
| `ls-npm-management` | Manage Nginx Proxy Manager proxy hosts via REST API; coordinate Docker + NPM deploy workflows |
| `ls-keepass-secrets` | KeePass-backed secrets via logical IDs; get/ensure credentials; bulk create or rotate; use when user asks for logins or workflow needs credentials |
| `ls-scrapling` | Host-first Scrapling integration; install and upgrade Scrapling via pipx, run single-URL extractions (simple HTML/Markdown/text or structured JSONL), and keep adapters aligned with Scrapling releases for web scraping and crawling tasks |
| `ls-omniroute-proxy` | Read-only OmniRoute proxy discovery, catalogs, provider metadata, limits, quotas, routing combos, MCP/A2A integration, and agent client configuration |
| `ls-omniroute-admin-automation` | OmniRoute administration automation for providers, nodes, aliases, combos, fallbacks, keys, policies, budgets, backup/restore, sync, and drift reconciliation |
| `ls-kilo-boss-orchestrator` | Kilo headless boss-worker orchestration with repo-local state, watchdog leases, consensus validation, and safety gates |
| `ls-kilo-visual-output` | Kilo CLI visual output organization guide with structured question, option, rationale, and execution summary patterns |

Skills follow the [Agent Skills](https://agentskills.io/specification) specification and are interchangeable with other spec-compliant hosts (import from URLs or local path; export framework skills for use elsewhere). See [SKILLS_AND_RULES.md](docs/SKILLS_AND_RULES.md), [PLATFORM_REGISTRY.md](docs/PLATFORM_REGISTRY.md), [SKILL_INTEROPERABILITY.md](docs/SKILL_INTEROPERABILITY.md), and [SKILL_IMPORTING.md](docs/SKILL_IMPORTING.md) for platform paths, loading behavior, and import/export.

---

## Tools

Run from **client repo root** (so that `_localsetup/` is present). Tools live under `_localsetup/tools/`. Use Bash from Linux, macOS, or WSL2 for bootstrap wrappers; v3 framework logic lives in Python under `_localsetup/tools/localsetup_v3.py` and `_localsetup/v3/`.

| Tool | Purpose |
|------|---------|
| `localsetup_v3.py` | Plan, install, update, verify, rollback, generate docs, and build packages. Usage: `python3 _localsetup/tools/localsetup_v3.py plan --platforms codex,kilo`. |
| `verify_context` / `verify_context.ps1` | Verify Cursor context file exists (`.cursor/rules/ls-context.mdc`). |
| `verify_rules` / `verify_rules.ps1` | Check git repo, data_paths (sh/ps1), and skills directory. |
| `skill_importer_scan` / `skill_importer_scan.ps1` | Scan a directory for Agent Skills; output per-skill brief (what it does, what it has, code types) and heuristic security flags. Use after fetching a URL or for a local path; then use skill-importer workflow to let the user select which skills to import. |
| `tmux_ops` / `tmux_ops.py` | Tmux ops workflow: pick session (idle = prompt on current line), probe sudo (ready vs password_required), send with pylon-guard delay, `send --wait` for adaptive idle detection, standalone `wait --timeout N` for long ops. When REMOTE_TMUX_HOST is set, wrapper runs the Python tool over SSH. See [docs/ops/tmux-ops-remote.md](docs/ops/tmux-ops-remote.md). |
| `tmux_terminal_mode` / `tmux_terminal_mode.py` | Toggle tmux-default terminal mode: `enable` (ide or shell layer + agent rule), `disable` (restore originals), `status` (all layers). See [docs/TMUX_TERMINAL_MODE.md](docs/TMUX_TERMINAL_MODE.md). |
| `agentq_transport_client/agentq_cli.py` | Agent Q transport: ship-file-drop, ingest-blob, file-drop-poll, ship-mail-strict, queue-pending, archive-prune. See [docs/AGENTIC_AGENT_Q_SCENARIOS.md](docs/AGENTIC_AGENT_Q_SCENARIOS.md) and client USER_GUIDE. |

---

## Libraries and configuration

- **`lib/data_paths.sh`** / **`lib/data_paths.ps1`**  - Path resolution: engine dir, project root, user data dir, ensure user data dir. Use in scripts for repo-local paths. Respects `LOCALSETUP_PROJECT_ROOT`, `LOCALSETUP_FRAMEWORK_DIR`, `LOCALSETUP_PROJECT_DATA`.
- **`lib/json_formatter.sh`**  - JSON formatting helpers for Bash scripts.
- **`discovery/core/os_detector.py`**  - OS detection (canonical; Linux, macOS, Windows). **`os_detector.sh`** / **`os_detector.ps1`** are thin launchers.
- **`config/defaults/system_config.yaml`**  - Defaults: `framework_folder: _localsetup`, `user_data_subdir: .localsetup-project`.

---

## Workflows

| Workflow | Description | When to use | Impact review |
|----------|-------------|-------------|---------------|
| Master rule / context | Always-loaded framework context | Always | No |
| Decision tree | One Q per turn, 4 options A–D, preferred + rationale | User says "decision tree" or "reverse prompt" | No |
| Agent Q (queue) | Process specs in `.agent/queue/` (or structured `in/`); implement, status, outcome | "Process PRDs", "run batch from PRD folder" | Yes if destructive |
| Agent Q bidirectional | Mail/file_drop adapters + OpenPGP; client `tools/agentq_transport_client/` (ACTIVE); protocol AGENTIC_AGENT_TO_AGENT_PROTOCOL.md | Agent-to-agent PRD handoff | Yes if destructive ship |
| Umbrella workflow | Multi-phase single kickoff; named workflows | User invokes by name | Yes for big/destructive |
| Manual (lazy admin) | Human-in-the-loop; three-block format; info-gather before destructive | Sudo, confirmation, manual steps | No (protocol is guardrail) |

See [WORKFLOW_REGISTRY.md](docs/WORKFLOW_REGISTRY.md) and [AGENTIC_DESIGN_INDEX.md](docs/AGENTIC_DESIGN_INDEX.md) for details.

---

## Verification and testing

From **client repo root**:

**Bash (Linux/macOS):**
```bash
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
./_localsetup/tests/automated_test.sh
```

**Windows:** Use WSL2 and run the Bash/Linux commands above.

The automated test runs path resolution, OS detection, and checks for `lib/`, the v3 CLI, `skills/`, and `templates/` under the engine directory.

---

Copyright (c) 2026 Crux Experts LLC. This framework is released under the [MIT License](https://opensource.org/license/MIT). You may use, copy, modify, merge, publish, distribute, sublicense, and create derivative works, provided the copyright notice and permission notice are included in all copies or substantial portions. See the repository root [LICENSE](../LICENSE) for the full text (when the repo is at `_localsetup/`, the root is one level up from `_localsetup/`).

**Contributing:** See the repository root [CONTRIBUTING.md](../CONTRIBUTING.md). **Security:** See [SECURITY.md](../SECURITY.md). **Where to get help:** Open an [Issue](https://github.com/cptnfren/localsetup/issues) or [Discussion](https://github.com/cptnfren/localsetup/discussions), or refer to the docs in `_localsetup/docs/` after installation.

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

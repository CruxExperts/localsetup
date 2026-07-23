---
status: ACTIVE
version: 4.3
owner_skill: ls-docs-organization
---

# Features

This is the full public capability catalog for Localsetup. The [root README](../../README.md) explains the pitch; this page lists what the framework actually provides.

## Generated Facts

<!-- facts-block:start -->
- Current version: `4.3.1`
- Supported platforms: `codex, claude-code, cursor, kilo, opencode, openclaw`
- Shipped skills: `103`
- Workflow packages: `24`
- Source: `ls/docs/_generated/facts.json`
<!-- facts-block:end -->

## Engine And Install

| Capability | What it gives you |
|---|---|
| Global framework source | The registered source checkout carries `ls/`; consuming repos keep `.localsetup/` state and selected adapters, not copied framework source. |
| Python-first Localsetup installer | Bash bootstrap delegates planning, dependency handling, install, verify, and rollback to `ls/tools/localsetup.py`. |
| Explicit multi-platform adapters | One install can attach selected Cursor, Claude Code, Codex CLI, OpenClaw, Kilo, and OpenCode adapter paths to the same managed package library. |
| Managed home library | Skills and workflow packages install to `~/.local/share/localsetup/packages`; explicitly selected adapters point there by symlink or use portable copies. |
| Lock and rollback metadata | `.localsetup/lock.json` and managed-path reports make installs inspectable and reversible. |
| Repair handoff and runtime split | `doctor repair` separates managed lock state from local runtime state, preserves custom content, emits compact handoff prompts, and records repair queue metadata. |
| Client registry and platform projection | `ls/config/clients.yaml` is the canonical source for client capabilities and adapter mappings; generated `ls/config/platforms.yaml` is the compatibility/runtime projection consumed by existing platform tooling. |

## Skills And Interoperability

| Capability | What it gives you |
|---|---|
| Agent Skills compliance | Shipped skills use spec-compatible `SKILL.md` packages with `name`, `description`, and `metadata.version`. |
| 103 shipped skills plus 24 workflow packages | Practical capabilities and orchestration flows for debugging, tests, PR review, git recovery, service triage, patching, docs, MCP building, context indexing, TypeScript code quality, OmniRoute integration, opt-in heartbeat harnessing, repo finalization, and more. |
| Skill import | Import skills from a URL or local path with discovery, validation, heuristic security screening, and summaries. |
| Skill vetting | Treat third-party skills as untrusted before they can influence agent behavior. |
| Skill normalization | Clean imported or in-tree skills for spec compliance, platform-neutral wording, and framework tooling standards. |
| Skill discovery | Maintain a public registry/index and recommend similar skills when creating or importing. |

## Workflow Control

| Capability | What it gives you |
|---|---|
| Workflow registry | Named workflows, aliases, and impact expectations for repeatable agent behavior. |
| First-class workflow packages | Workflow sources live under `ls/workflows/ls-workflow-*`, include executable `SKILL.md` files, and carry Localsetup `workflow.yaml` metadata for dependencies, gates, phases, validation, and generated catalogs. |
| Opt-in harness automation | The `harness` pack installs Codex heartbeat capability only; target config, cron entries, and runtime state are created only by explicit `localsetup harness codex-heartbeat ...` activation commands. |
| Decision tree workflow | A reverse-prompt planning loop that asks one focused question at a time. |
| PRD batch workflow | Queue-driven spec execution with status updates and outcome records. |
| Agent Q transport | Bidirectional PRD/spec exchange over file_drop or mail with sealed payloads, registry checks, and ledgering. |
| Composite pipelines | Higher-level flows such as PR feedback, git repair, server triage, and repo polish built from existing skills. |
| Git traceability | Specs, outcomes, and decisions can reference commits so work is auditable later. |

## Safety And Operations

| Capability | What it gives you |
|---|---|
| Human-in-the-loop tmux ops | Privileged or risky operations stay visible in tmux with sudo readiness checks and resumable output. |
| Transaction-safe heartbeat runs | Codex heartbeat writes staged artifacts, validates hashes, promotes atomically, and recovers interrupted staged runs before fresh work starts. |
| Safety and backup guidance | Skills route destructive ops through conservative backup, temp-file, firewall, and approval practices. |
| Input hardening | Framework docs and tooling policy require hostile-input treatment for CLI args, files, network payloads, and imported content. |
| Security-aware skill import | Prompt-injection and suspicious-pattern heuristics run before imported skills become part of the library. |
| Markdown/reference validation | Public docs and skill references can be checked for broken local links and anchors. |

## Release And Maintenance

| Capability | What it gives you |
|---|---|
| Patch-default release versioning | Routine commit batches advance one patch by default; `Release-Type:` trailers explicitly request major, minor, patch, or no bump. |
| Generated facts sync | README and docs facts blocks stay aligned with `VERSION`, platform count, skill count, and workflow package count. |
| Automated documentation alignment | `ls/tools/docs_alignment.py` inventories repo docs, maps source-truth claims, validates assets and links, refreshes generated artifacts, and supports CI checks. |
| Skill metadata versions | Skill versions are tracked separately from framework release versions. |
| Framework audit | Doc, link, skill matrix, version, facts, and smoke checks before release. |
| Public package boundary | Packaging and scan commands keep generated/runtime artifacts out of source releases. |

## High-Value Shipped Skills

| Skill | Use it for |
|---|---|
| `ls-agentlens` | Codebase navigation and module discovery. |
| `ls-debug-pro` | Systematic debugging across languages and failure types. |
| `ls-test-runner` | Writing and running test suites across common frameworks. |
| `ls-typescript-code-quality` | TypeScript, TSX, tsconfig, typed linting, Node TypeScript scripts, and framework-heavy TypeScript changes. |
| `ls-pr-reviewer` | Risk-focused PR review and missing-test detection. |
| `ls-mcp-builder` | Building MCP servers for agent/tool interoperability. |
| `ls-skill-importer` | Bringing in skills from external sources safely. |
| `ls-skill-vetter` | Reviewing third-party skills before install. |
| `ls-workflow-ops-tmux-session` | Visible human-gated operations on local or remote machines. |
| `ls-workflow-tmux-terminal-mode` | Tmux-default terminal mode setup and read-only health checks. |
| `ls-linux-service-triage` | Diagnosing Linux service, reverse proxy, process, and DNS failures. |
| `ls-automatic-versioning` | Keeping framework version, generated docs, and release behavior aligned. |

Full catalogs: [SKILLS.md](SKILLS.md), [WORKFLOW_PACKAGES.md](WORKFLOW_PACKAGES.md), and [WORKFLOW_QUICK_REF.md](WORKFLOW_QUICK_REF.md).

## Next Steps

- [Quickstart](QUICKSTART.md)
- [Platform registry](PLATFORM_REGISTRY.md)
- [Workflow packages](WORKFLOW_PACKAGES.md)
- [Workflow registry](WORKFLOW_REGISTRY.md)
- [Skill importing](SKILL_IMPORTING.md)
- [Versioning](VERSIONING.md)

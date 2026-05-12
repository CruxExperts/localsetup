# Localsetup v3

<p align="center">
  <img src="assets/localsetup-v3-readme-hero.png" alt="Localsetup v3 visual: repo-local agent workflow framework" width="960">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://agentskills.io/specification"><img src="https://img.shields.io/badge/Agent%20Skills-compatible-2ea44f" alt="Agent Skills compatible"></a>
  <a href="_localsetup/docs/PLATFORM_REGISTRY.md"><img src="https://img.shields.io/badge/platforms-cursor%20%7C%20claude--code%20%7C%20codex%20%7C%20openclaw%20%7C%20kilo%20%7C%20opencode-1f6feb" alt="Supported platforms"></a>
</p>

**Version:** 3.2.5<br>

**Localsetup v3 gives coding agents a real operating layer inside your repo.**

Recent research signals from 2025 and 2026 show the same pressure from different angles: AI coding work is growing fast, agent teams still struggle with durable context and review, and developers remain cautious about AI accuracy. That is the gap Localsetup is built for.

Localsetup v3 turns your repository into the source of truth for agent context, skills, workflows, safety gates, install state, and release evidence. It is not another chat prompt collection. It is a portable framework with adapters for Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, Kilo, and OpenCode, plus a disciplined skill library and predictable workflow model.

Use it when you want agents to stop improvising and start working from auditable context.

## The short version

Localsetup v3 packages:

- Repo-local framework source under `_localsetup/`
- 45 shipped capability skills plus 16 first-class workflow packages for debugging, testing, PR review, infrastructure, docs, git recovery, skill import, security vetting, and agent workflow control
- Cross-platform adapters for Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, Kilo, and OpenCode
- Agent Skills-compatible `SKILL.md` packages that can be imported, normalized, vetted, installed, and reused
- Workflow packages under `_localsetup/workflows/` that stay executable as skills while carrying Localsetup `workflow.yaml` metadata for aliases, gates, dependencies, and generated registries
- A Python-first installer with preflight, planning, verification, rollback metadata, and generated docs sync
- Human-in-the-loop operations for risky commands, remote/server work, and sudo-aware tmux sessions

That means your agent setup travels with the repo, survives context resets, and can be reviewed like code.

## How it fits together

<p align="center">
  <img src="assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, config resolver, managed home library, adapters, and rollback metadata" width="960">
</p>

`_localsetup/` is the canonical source. The installer resolves configuration, creates the managed home library for skills and workflow packages, attaches only explicitly selected platform adapter paths, writes lock/report metadata, and leaves rollback evidence behind. Generated adapter trees are install output, not framework source.

## Skills and workflow packages

Localsetup v3 makes one important distinction explicit:

| Package type | Source root | Runtime shape | Use it for |
|---|---|---|---|
| Capability skill | `_localsetup/skills/ls-*` | Agent Skills `SKILL.md` package | A reusable capability such as debugging, testing, skill import, PR review, service triage, or versioning. |
| Workflow package | `_localsetup/workflows/ls-workflow-*` | Agent Skills `SKILL.md` package plus `workflow.yaml` | A named orchestration flow with aliases, required skills, gates, phases, validation, and expected outputs. |

Both package types install into `~/.local/share/agents/skills/localsetup`, so agent hosts can invoke them through explicitly attached adapter paths. The split keeps portable skills clean while making workflow orchestration auditable and generated from source manifests.

Start with the [workflow packages guide](_localsetup/docs/WORKFLOW_PACKAGES.md) for usage and the [workflow standard](_localsetup/docs/WORKFLOW_STANDARD.md) for authoring rules.

## Current snapshot

<!-- facts-block:start -->
| Fact | Value |
|---|---|
| Current version | `3.2.5` |
| Supported platforms | `cursor, claude-code, codex, openclaw, kilo, opencode` |
| Shipped skills | `45` |
| Workflow packages | `17` |
| Source | `_localsetup/docs/_generated/facts.json` |
<!-- facts-block:end -->

## 60-second quickstart

Global bootstrap from any directory on Linux, macOS, or WSL2:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --
```

This opens an interactive terminal wizard. It creates or refreshes the managed source checkout, explains what will be changed, lets you choose whether to attach agent adapters, and asks for confirmation before applying.

Every wizard step shows the same shortcuts before you answer: `Enter number(s) | d details | b back | q quit | ? help`. Detailed mode is on by default, so menu rows explain what each choice does, when to choose it, and the tradeoff. Press `d` at any prompt for compact mode; compact mode still keeps the one-line summary for each option.

The wizard stays dependency-free and line-oriented. It uses semantic color and simple status glyphs only when the terminal supports them; `NO_COLOR`, `TERM=dumb`, non-TTY output, `--no-color`, and `--color never` keep output free of ANSI color. Use `--color always` or `--glyphs unicode` only for an interactive terminal where you explicitly want that rendering; `--glyphs ascii` keeps portable labels such as `[OK]`, `[WARN]`, and `[FAIL]`.

The legacy public form still opens the same wizard when a terminal is available:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --yes --tools codex
```

Selecting tools in the wizard, or passing `--tools` / `--platforms`, attaches adapters such as `.codex/skills` to the chosen target. If you do not select tools, the install is global-library-only.

For automation, opt in explicitly:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --non-interactive --yes
```

Automation mode preserves machine-readable output. Without a terminal, the installer asks you to rerun with a TTY or with `--non-interactive --yes`.

From a cloned checkout, open the same wizard:

```bash
./install --directory .
```

The local checkout command uses that checkout as the registered source. Like the raw global bootstrap, it installs the managed skill library and creates no repo adapter paths unless you pass `--tools` or `--platforms`. Both paths also create a managed user command at `~/.local/bin/localsetup`. After registration, run Localsetup from any project:

```bash
localsetup install --tools codex --yes
```

When invoked through the managed command, Localsetup uses the registered framework checkout as the source and the nearest Git worktree root from your current directory as the target. Outside Git, it targets the current directory. Use `--target-directory /path/to/project` to override that target.

Attach adapters only for the hosts you choose:

```bash
localsetup install --tools codex,kilo --yes
```

Install every shipped skill and workflow package for Codex, Kilo, and OpenCode, while preparing the managed Python dependency environment:

```bash
./install --directory . --tools codex,kilo,opencode --packs bootstrap,core,dev,ops,integrations,publishing,experimental --install-deps
```

Attach a selected adapter to another repo while using this checkout as the source:

```bash
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor
```

To convert a repo that may contain old Localsetup files or adapter paths, start with a dry report and apply only after blockers are clear:

```bash
localsetup convert --tools codex --packs core
localsetup convert --tools codex --packs core --yes
```

Conversion writes a timestamped backup and machine-readable report under `.localsetup/backups/conversion-*`, archives known managed or legacy Localsetup artifacts, blocks ambiguous unmanaged content, syncs the current framework source when needed, installs selected adapters, and verifies the result.

Windows support is WSL2-only in v3. Open WSL2, change to the repo path, and run the Bash installer. `install.ps1` is a compatibility guidance stub.

Full install docs: [_localsetup/docs/QUICKSTART.md](_localsetup/docs/QUICKSTART.md) and [_localsetup/docs/MULTI_PLATFORM_INSTALL.md](_localsetup/docs/MULTI_PLATFORM_INSTALL.md).

## 10 reasons to use Localsetup v3

1. **Your agent context becomes code.** Instructions, skills, workflows, platform manifests, and docs live in the repo, so changes are visible in git instead of hidden in a local profile or a forgotten prompt.
2. **One skill library reaches multiple agent hosts.** When selected with `--tools` or `--platforms`, the shipped adapters let Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, Kilo, and OpenCode attach to the same managed Localsetup skill library.
3. **It leans into the Agent Skills standard.** Skills use spec-compatible `SKILL.md` frontmatter, which makes them easier to import, export, normalize, and share across ecosystems.
4. **It tackles the trust gap directly.** The framework pushes agents toward repeatable workflows, explicit verification, documented assumptions, and human gates instead of one-off "looks good" responses.
5. **It treats skill imports as supply-chain events.** External skills are discovered, validated, security-screened, summarized, and normalized before they become part of your library.
6. **It helps with the work developers actually hand agents.** Debugging, tests, PR review, codebase navigation, docs cleanup, git recovery, MCP building, Linux service triage, patching, and release chores are covered out of the box.
7. **It has safety rails for real machines.** Server and operations workflows route through tmux, sudo probing, backup/safety guidance, and explicit approval points for risky actions.
8. **It gives long-running work a shape.** First-class workflow packages, decision trees, PRD queues, Agent Q handoffs, generated registries, and outcome templates make multi-step agent work easier to restart, audit, and delegate.
9. **It makes installs reversible.** The v3 installer plans, applies, verifies, writes lock metadata, and can roll back managed paths without treating generated adapter output as source.
10. **It keeps releases tidy.** Version sync, generated facts, skill metadata versions, framework audit, and Conventional Commit release tooling reduce the drift that makes public repos feel abandoned.

## 10 shipped packages worth starting with

These are not toy prompts. They are practical skills and workflows from the shipped library.

| Package | Why it matters |
|---|---|
| `ls-agentlens` | Helps agents explore larger codebases through structured navigation instead of blind file-hopping. |
| `ls-debug-pro` | Gives debugging a repeatable method across Node, Python, Swift, network issues, and git bisect. |
| `ls-test-runner` | Guides test creation and execution across pytest, Jest, Vitest, Playwright, and XCTest. |
| `ls-pr-reviewer` | Turns PR review into a structured risk hunt: diff analysis, security concerns, test gaps, and style issues. |
| `ls-mcp-builder` | Helps build high-quality MCP servers for current agent/tool interoperability workflows. |
| `ls-skill-importer` | Imports skills from URLs or local paths with discovery, validation, security screening, and summaries. |
| `ls-skill-vetter` | Reviews third-party skills as untrusted inputs before they join your agent environment. |
| `ls-workflow-ops-tmux-session` | Keeps human-controlled server operations visible, resumable, and sudo-aware. |
| `ls-linux-service-triage` | Diagnoses service failures with logs, systemd/PM2, file permissions, reverse proxy checks, and DNS sanity checks. |
| `ls-automatic-versioning` | Keeps `VERSION`, README values, generated docs, and release behavior aligned with Conventional Commits. |

See the generated catalogs for all shipped skills and workflows: [_localsetup/docs/SKILLS.md](_localsetup/docs/SKILLS.md) and [_localsetup/docs/WORKFLOW_QUICK_REF.md](_localsetup/docs/WORKFLOW_QUICK_REF.md).

## Install lifecycle

<p align="center">
  <img src="assets/localsetup-v3-install-lifecycle.svg" alt="Localsetup v3 install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

The Bash wrapper stays thin. The Python CLI handles preflight, dependency setup, adapter planning, managed skill installation, verification, generated docs, packaging, and rollback.

Useful commands:

```bash
localsetup doctor
localsetup verify --tools codex
python3 _localsetup/tools/localsetup_v3.py doctor
python3 _localsetup/tools/localsetup_v3.py --repo . context --markdown
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --repo . rollback
```

## What Localsetup is solving

The 2025 agent tooling story is exciting, but the hard parts are not magic. Teams still need context that survives across sessions, standards that work across tools, safety around imported instructions, and workflows that can be resumed by another human or agent without archaeology.

Localsetup's opinion is simple: keep the agent operating model close to the code. Make it installable. Make it reviewable. Make it boring enough to trust.

Research signals behind the design, verified in May 2026:

- [GitHub Octoverse 2025](https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/) reports rapid growth in AI projects and LLM SDK use on GitHub.
- [LangChain State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering) highlights human review, evals, model/tool choices, and production agent patterns.
- [Stack Overflow 2025 AI survey](https://survey.stackoverflow.co/2025/ai) reports high AI tool use alongside low trust in AI accuracy.
- [Gartner's 2025 engineering leader survey](https://www.gartner.com/en/newsroom/press-releases/2025-05-22-gartner-survey-finds-77-percent-of-engineering-leaders-identify-ai-integration-in-apps-as-a-major-challenge) frames AI integration into applications as a significant engineering challenge.
- [OWASP LLM Top 10 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/) keeps prompt injection, sensitive information disclosure, supply-chain issues, and excessive agency in view.
- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro) and [Agent Skills](https://agentskills.io/specification) are current interoperability standards for tools, context, and skills.

## Requirements

- Python `>= 3.10`
- Bash on Linux, macOS, or WSL2
- Git and network access to GitHub for raw bootstrap, unless installing from a local clone
- Recommended: `rg`, `pip`, and the packages in `_localsetup/requirements.txt`

Use managed dependency setup instead of system pip overrides:

```bash
./install --directory . --install-deps
```

## Read more

- [Framework docs index](_localsetup/docs/README.md)
- [Framework README](_localsetup/README.md)
- [Feature catalog](_localsetup/docs/FEATURES.md)
- [Platform registry](_localsetup/docs/PLATFORM_REGISTRY.md)
- [Workflow packages](_localsetup/docs/WORKFLOW_PACKAGES.md)
- [Workflow standard](_localsetup/docs/WORKFLOW_STANDARD.md)
- [Workflow registry](_localsetup/docs/WORKFLOW_REGISTRY.md)
- [Skill importing](_localsetup/docs/SKILL_IMPORTING.md)
- [Skill discovery](_localsetup/docs/SKILL_DISCOVERY.md)
- [Contributing](CONTRIBUTING.md)
- [Support](SUPPORT.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Security](SECURITY.md)

## License

Localsetup is released under the [MIT License](LICENSE).

## Community and Support

For bugs, use the bug report form and include the Localsetup version, platform ID, command, expected result, actual result, and validation output. For feature requests, use the feature form and name the affected skill, workflow package, platform, or docs area. For version-sync, generated-doc, publish, or package-artifact problems, use the maintenance form.

Use [GitHub Discussions](https://github.com/CruxExperts/localsetup/discussions) for usage questions and early design conversation. Report security-sensitive issues through private vulnerability reporting when available; otherwise open a minimal public issue asking for a secure contact without details.

# Localsetup v3

<p align="center">
  <img src="assets/localsetup-v3-readme-hero.png" alt="Localsetup v3 visual: repo-local agent workflow framework" width="960">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://agentskills.io/specification"><img src="https://img.shields.io/badge/Agent%20Skills-compatible-2ea44f" alt="Agent Skills compatible"></a>
  <a href="_localsetup/docs/PLATFORM_REGISTRY.md"><img src="https://img.shields.io/badge/platforms-cursor%20%7C%20claude--code%20%7C%20codex%20%7C%20openclaw%20%7C%20kilo%20%7C%20opencode-1f6feb" alt="Supported platforms"></a>
</p>

**Version:** 3.0.2<br>

**Localsetup v3 gives coding agents a real operating layer inside your repo.**

AI coding tools are everywhere now. GitHub reports fast growth in AI projects and coding-agent activity, LangChain's agent engineering survey calls out context engineering as a recurring pain point, and Stack Overflow's 2025 survey shows the awkward truth: developers are using AI more while trusting it less. That is the gap Localsetup is built for.

Localsetup v3 turns your repository into the source of truth for agent context, skills, workflows, safety gates, install state, and release evidence. It is not another chat prompt collection. It is a portable framework that lets Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, Kilo, and OpenCode share a disciplined skill library and a predictable workflow model.

Use it when you want agents to stop improvising and start working from auditable context.

## The short version

Localsetup v3 packages:

- Repo-local framework source under `_localsetup/`
- 49 shipped skills for debugging, testing, PR review, infrastructure, docs, git recovery, skill import, security vetting, and agent workflow control
- Cross-platform adapters for Cursor, Claude Code, Codex CLI, OpenClaw, Kilo, and OpenCode
- Agent Skills-compatible `SKILL.md` files that can be imported, normalized, vetted, and reused
- A Python-first installer with preflight, planning, verification, rollback metadata, and generated docs sync
- Human-in-the-loop operations for risky commands, remote/server work, and sudo-aware tmux sessions

That means your agent setup travels with the repo, survives context resets, and can be reviewed like code.

## How it fits together

<p align="center">
  <img src="assets/localsetup-v3-architecture.svg" alt="Localsetup v3 architecture: repo source, config resolver, managed home library, adapters, and rollback metadata" width="960">
</p>

`_localsetup/` is the canonical source. The installer resolves configuration, creates the managed home skill library, attaches platform adapter paths, writes lock/report metadata, and leaves rollback evidence behind. Generated adapter trees are install output, not framework source.

## Current snapshot

<!-- facts-block:start -->
| Fact | Value |
|---|---|
| Current version | `3.0.2` |
| Supported platforms | `cursor, claude-code, codex, openclaw, kilo, opencode` |
| Shipped skills | `49` |
| Source | `_localsetup/docs/_generated/facts.json` |
<!-- facts-block:end -->

## 60-second quickstart

Run from a project root on Linux, macOS, or WSL2.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash
```

Or from a cloned checkout:

```bash
./install --directory . --yes
```

Limit adapter creation when you only want specific hosts:

```bash
./install --directory . --tools codex,kilo --yes
```

Windows support is WSL2-only in v3. Open WSL2, change to the repo path, and run the Bash installer. `install.ps1` is a compatibility guidance stub.

Full install docs: [_localsetup/docs/QUICKSTART.md](_localsetup/docs/QUICKSTART.md) and [_localsetup/docs/MULTI_PLATFORM_INSTALL.md](_localsetup/docs/MULTI_PLATFORM_INSTALL.md).

## 10 reasons to use Localsetup v3

1. **Your agent context becomes code.** Instructions, skills, workflows, platform manifests, and docs live in the repo, so changes are visible in git instead of hidden in a local profile or a forgotten prompt.
2. **One skill library reaches multiple agent hosts.** Cursor, Claude Code, Codex CLI, OpenClaw, Kilo, and OpenCode can all attach to the same managed Localsetup skill library.
3. **It leans into the Agent Skills standard.** Skills use spec-compatible `SKILL.md` frontmatter, which makes them easier to import, export, normalize, and share across ecosystems.
4. **It tackles the trust gap directly.** The framework pushes agents toward repeatable workflows, explicit verification, documented assumptions, and human gates instead of one-off "looks good" responses.
5. **It treats skill imports as supply-chain events.** External skills are discovered, validated, security-screened, summarized, and normalized before they become part of your library.
6. **It helps with the work developers actually hand agents.** Debugging, tests, PR review, codebase navigation, docs cleanup, git recovery, MCP building, Linux service triage, patching, and release chores are covered out of the box.
7. **It has safety rails for real machines.** Server and operations workflows route through tmux, sudo probing, backup/safety guidance, and explicit approval points for risky actions.
8. **It gives long-running work a shape.** Decision trees, PRD queues, Agent Q handoffs, workflow registries, and outcome templates make multi-step agent work easier to restart, audit, and delegate.
9. **It makes installs reversible.** The v3 installer plans, applies, verifies, writes lock metadata, and can roll back managed paths without treating generated adapter output as source.
10. **It keeps releases tidy.** Version sync, generated facts, skill metadata versions, framework audit, and Conventional Commit release tooling reduce the drift that makes public repos feel abandoned.

## 10 shipped skills worth starting with

These are not toy prompts. They are practical workflows from the shipped library.

| Skill | Why it matters |
|---|---|
| `ls-agentlens` | Helps agents explore larger codebases through structured navigation instead of blind file-hopping. |
| `ls-debug-pro` | Gives debugging a repeatable method across Node, Python, Swift, network issues, and git bisect. |
| `ls-test-runner` | Guides test creation and execution across pytest, Jest, Vitest, Playwright, and XCTest. |
| `ls-pr-reviewer` | Turns PR review into a structured risk hunt: diff analysis, security concerns, test gaps, and style issues. |
| `ls-mcp-builder` | Helps build high-quality MCP servers, which matters as agent/tool interoperability becomes standard infrastructure. |
| `ls-skill-importer` | Imports skills from URLs or local paths with discovery, validation, security screening, and summaries. |
| `ls-skill-vetter` | Reviews third-party skills as untrusted inputs before they join your agent environment. |
| `ls-tmux-shared-session-workflow` | Keeps human-controlled server operations visible, resumable, and sudo-aware. |
| `ls-linux-service-triage` | Diagnoses service failures with logs, systemd/PM2, file permissions, reverse proxy checks, and DNS sanity checks. |
| `ls-automatic-versioning` | Keeps `VERSION`, README values, generated docs, and release behavior aligned with Conventional Commits. |

See the generated catalog for all 49 skills: [_localsetup/docs/SKILLS.md](_localsetup/docs/SKILLS.md).

## Install lifecycle

<p align="center">
  <img src="assets/localsetup-v3-install-lifecycle.svg" alt="Localsetup v3 install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

The Bash wrapper stays thin. The Python CLI handles preflight, dependency setup, adapter planning, managed skill installation, verification, generated docs, packaging, and rollback.

Useful commands:

```bash
python3 _localsetup/tools/localsetup_v3.py doctor
python3 _localsetup/tools/localsetup_v3.py --repo . context --markdown
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --repo . rollback
```

## What Localsetup is solving

The 2025 agent tooling story is exciting, but the hard parts are not magic. Teams still need context that survives across sessions, standards that work across tools, safety around imported instructions, and workflows that can be resumed by another human or agent without archaeology.

Localsetup's opinion is simple: keep the agent operating model close to the code. Make it installable. Make it reviewable. Make it boring enough to trust.

Research signals behind the design:

- [GitHub Octoverse 2025](https://github.blog/news-insights/octoverse/octoverse-a-new-developer-joins-github-every-second-as-ai-leads-typescript-to-1/) points to rapid AI project growth, coding-agent activity, and MCP adoption.
- [LangChain State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering) highlights context engineering, human review, evals, and everyday use of coding agents.
- [Stack Overflow 2025 AI survey](https://survey.stackoverflow.co/2025/ai) shows that AI usage is high while trust in AI accuracy has fallen.
- [Gartner](https://www.gartner.com/en/newsroom/press-releases/2025-05-22-gartner-survey-finds-77-percent-of-engineering-leaders-identify-ai-integration-in-apps-as-a-major-challenge) reports AI integration as a major challenge for engineering leaders.
- [OWASP LLM Top 10 2025](https://owasp.org/www-project-top-10-for-large-language-model-applications/) keeps prompt injection, sensitive information disclosure, supply-chain issues, and excessive agency in view.
- [Model Context Protocol](https://modelcontextprotocol.io/docs/getting-started/intro) and [Agent Skills](https://agentskills.io/specification) show the ecosystem moving toward interoperable agent capabilities instead of isolated prompt piles.

## Requirements

- Python `>= 3.10`
- Bash on Linux, macOS, or WSL2
- Git for clone/update workflows
- Recommended: `rg`, `pip`, and the packages in `_localsetup/requirements.txt`

Use managed dependency setup instead of system pip overrides:

```bash
./install --directory . --yes --install-deps
```

## Read more

- [Framework docs index](_localsetup/docs/README.md)
- [Framework README](_localsetup/README.md)
- [Feature catalog](_localsetup/docs/FEATURES.md)
- [Platform registry](_localsetup/docs/PLATFORM_REGISTRY.md)
- [Workflow registry](_localsetup/docs/WORKFLOW_REGISTRY.md)
- [Skill importing](_localsetup/docs/SKILL_IMPORTING.md)
- [Skill discovery](_localsetup/docs/SKILL_DISCOVERY.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

## License

Localsetup is released under the [MIT License](LICENSE).

For help, open a GitHub Issue or Discussion in this repository.

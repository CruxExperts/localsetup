# Localsetup v2

<p align="center">
  <img src="assets/localsetup-v2-logo.png" alt="Localsetup v2" width="160">
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://agentskills.io/specification"><img src="https://img.shields.io/badge/Agent%20Skills-compatible-2ea44f" alt="Agent Skills compatible"></a>
  <a href="_localsetup/docs/PLATFORM_REGISTRY.md"><img src="https://img.shields.io/badge/platforms-cursor%20%7C%20claude--code%20%7C%20codex%20%7C%20openclaw%20%7C%20kilo%20%7C%20opencode-1f6feb" alt="Supported platforms"></a>
</p>

**Version:** 2.12.0  
**Last updated:** 2026-04-01

Agentic setups often share the same headaches: indeterministic outcomes, memory that compresses or decays, hallucinations, agents that drop context or ignore instructions, and difficulty scaling beyond a certain code size. Coordinating multiple agents so they follow patterns and run workflows reliably is harder still. Localsetup v2 targets these problems without adding much overhead.

The framework is repo-local: context, skills, and docs live in one folder in your project. Clone or move the repo and the setup moves with it. No home-directory state, no cloud dependency. Context is code, so you can audit what changed and tie specs and outcomes to git commits. It installs with one command and works the same across Cursor, Claude Code, OpenAI Codex CLI, OpenClaw, and OpenCode (add more via [one registry file](_localsetup/docs/PLATFORM_REGISTRY.md)). Safety and sandboxing are built in; when you import third-party skills, the framework runs security checks and heuristics before anything touches your agent. Tooling can be refactored or rewritten in Python and standardized even when sources disagree, and you can adapt it to your stack. The [public skill index](_localsetup/docs/PUBLIC_SKILL_INDEX.yaml) grows over time; you can add your own registry sources and combine or adapt skills as you like. One folder in every project, no namespace collisions with existing code. It just works.

Out of the box you get [all shipped skills](_localsetup/docs/SKILLS.md): debugging, TDD, PR review, git recovery, Linux patching, Ansible, and more. Skills follow the [Agent Skills](https://agentskills.io/specification) spec, so you can import from other ecosystems (e.g. Anthropic's public repo) and export yours. Version and docs are maintained in a separate maintainer workflow; see [_localsetup/docs/VERSIONING.md](_localsetup/docs/VERSIONING.md). Run one install command, verify with one script, then use the workflows. The result is a single, auditable agent setup that stays accurate over time.

## 📊 Current snapshot

<!-- facts-block:start -->
| Fact | Value |
|---|---|
| Current version | `2.12.0` |
| Supported platforms | `` |
| Shipped skills | `50` |
| Source | `_localsetup/docs/_generated/facts.json` |
<!-- facts-block:end -->

## 🚀 60-second quickstart

Run from your project root. The installer prompts for directory and platform, so you do not need to memorize flags.

### Linux and macOS (Bash)

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash
```

`sudo curl ... | bash` only elevates curl; the install and deploy run as the current user. For a full install as root (e.g. to avoid root-owned files when re-running upgrades later): `curl -sSL <url> -o /tmp/install.sh && sudo bash /tmp/install.sh`.

### Windows (PowerShell)

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/cptnfren/localsetup/main/install.ps1)))
```

The installer asks which platform(s) to deploy: Cursor, Claude Code, Codex CLI, OpenClaw, Kilo, or OpenCode. After install, run the verification script printed at the end to confirm context loaded correctly.

For non-interactive one-liners (CI, automation, or when you already know the platform), see the collapsed **Full install reference** below or [_localsetup/docs/QUICKSTART.md](_localsetup/docs/QUICKSTART.md).

## 🌐 Global installation (optional)

Deploy the framework once to your user home directory and use it across ALL projects. Global deployment installs skills and rules to user-wide locations (`~/.codex/skills/`, `~/.config/kilo/`, `~/.openclaw/`, `~/.claude/`), making the framework available without per-repo installation.

### Linux and macOS (Bash)

```bash
# Auto-detect installed agents (kilo, openclaw, claude) and deploy globally
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --global

# Deploy to specific agents only
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --global --tools kilo

# From local clone
./install --global
```

### Windows (PowerShell)

```powershell
# Auto-detect and deploy globally
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/cptnfren/localsetup/main/install.ps1))) -Global

# Specific agents
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/cptnfren/localsetup/main/install.ps1))) -Global -Tools kilo
```

**Note:** Repo-local installation takes precedence over global. Project-specific skills and rules override global ones.

### Minimum requirements

- **Required:** `git >= 2.20.0`; on Linux/macOS, `rg` (ripgrep) is also required for the install script.
- **Recommended:** `python >= 3.10`, `pip`, and the packages in `_localsetup/requirements.txt` (PyYAML, requests, python-frontmatter). After install: `python3 -m pip install -r _localsetup/requirements.txt`, or pass `--install-deps` / `-InstallDeps` to install them automatically.

The installer runs a dependency preflight and prints missing items with copy-paste install suggestions before proceeding. Full list: [_localsetup/docs/MULTI_PLATFORM_INSTALL.md](_localsetup/docs/MULTI_PLATFORM_INSTALL.md#dependency-preflight).

## ⚡ Top 10 features

1. **Secure skill import with safety checks** - import any external skill or freeform text, run automatic prompt-injection detection, foreign-language screening, and heuristic security analysis before it touches your agent. Use the framework as a sandbox to build and adapt workflows however you see fit.
2. **Repo-local engine** - the entire framework lives at `_localsetup/`; clone or move your repo and everything travels together. No home-directory state, no cloud sync, no hidden drift.
3. **Multi-platform install** - one command deploys context and skills for Cursor, Claude Code, Codex CLI, OpenClaw, or OpenCode. Add platforms later by editing one registry file.
4. **Agent Skills spec compatible** - skills follow the open Agent Skills specification, so you can import from Anthropic's public repo, awesome lists, or your own library and export yours for others.
5. **Shipped skills** - debugging, TDD, PR review, git recovery, Linux patching, Ansible orchestration, codebase navigation (agentlens), tmux ops (pick/probe/send), system-info, cron-orchestrator, PRD batching, decision trees, and more, ready to use out of the box. See [_localsetup/docs/SKILLS.md](_localsetup/docs/SKILLS.md) for the full catalog.
6. **Workflow registry and quick-ref** - named workflow IDs, human-readable names, and aliases in [_localsetup/docs/WORKFLOW_REGISTRY.md](_localsetup/docs/WORKFLOW_REGISTRY.md), plus an agent-facing quick reference and composite pipelines (PR feedback loop, git repair and hygiene, server triage and patch, repo polish) in [_localsetup/docs/WORKFLOW_QUICK_REF.md](_localsetup/docs/WORKFLOW_QUICK_REF.md). Agents can invoke multi-step workflows by intent instead of chaining skills manually.
7. **Human-in-the-loop gates and Always-On-TMUX** - tmux shared sessions via tmux_ops (pick, probe, send with 1 s delay), sudo discovery and approval flow before destructive ops, and a tmux-default terminal mode that can run as an \"always-on tmux\" layer for this repo or machine. The agent pauses and waits for you when it matters.
8. **Versioning** - VERSION at repo root; conventional commits; version and docs are maintained in a separate maintainer workflow (see [_localsetup/docs/VERSIONING.md](_localsetup/docs/VERSIONING.md)).
9. **Skill metadata patching** - staged `SKILL.md` files get their `metadata.version` incremented automatically so skill docs stay accurate.
10. **Platform registry and git-coupled traceability** - a single [Markdown table](_localsetup/docs/PLATFORM_REGISTRY.md) defines every supported host, context path, and skills path, and PRDs/specs/outcomes can reference commit hashes for audit. Context is code; changes are reviewable.
11. **Global deployment (user-wide, cross-project)** - Install once, use the framework across all projects. Deploys skills to `~/.codex/skills/`, `~/.config/kilo/` (auto-discovered), `~/.openclaw/`, and `~/.claude/` with auto-detection of installed agents.

The full feature catalog contains additional capabilities. See [_localsetup/docs/FEATURES.md](_localsetup/docs/FEATURES.md) for details.

## 🛠️ Top 10 shipped skills

1. `localsetup-debug-pro` - systematic debugging methodology with language-specific commands.
2. `localsetup-test-runner` - write and run tests across frameworks (pytest, Jest, Vitest, Playwright).
3. `localsetup-pr-reviewer` - automated PR review with diff analysis, lint, and structured reports.
4. `localsetup-unfuck-my-git-state` - staged recovery for broken HEAD, phantom worktrees, missing refs.
5. `localsetup-linux-patcher` - automated server patching and Docker container updates.
6. `localsetup-ansible-skill` - playbook-driven provisioning and multi-host orchestration.
7. `localsetup-decision-tree-workflow` - reverse-prompt process: one question at a time, four options, rationale.
8. `localsetup-tmux-shared-session-workflow` - human-in-the-loop ops via tmux_ops (pick/probe/send); REMOTE_TMUX_HOST for remote/VMs.
9. `localsetup-skill-importer` - import external skills from URL or local path with security screening.
10. `localsetup-humanizer` - remove AI-writing patterns from text based on Wikipedia cleanup guide.

The generated shipped skills catalog lists all skills with descriptions and versions. See [_localsetup/docs/SKILLS.md](_localsetup/docs/SKILLS.md).

## 📚 Read more

- [Framework docs index](_localsetup/docs/README.md)
- [Framework README](_localsetup/README.md)
- [Platform registry](_localsetup/docs/PLATFORM_REGISTRY.md)
- [Workflow registry](_localsetup/docs/WORKFLOW_REGISTRY.md)
- [Skill importing](_localsetup/docs/SKILL_IMPORTING.md)
- [Skill discovery](_localsetup/docs/SKILL_DISCOVERY.md)
- [Contributing](CONTRIBUTING.md)
- [Security](SECURITY.md)

<details>
<summary>Full install reference</summary>

### Interactive installers

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash
```

```powershell
& ([scriptblock]::Create((irm https://raw.githubusercontent.com/cptnfren/localsetup/main/install.ps1)))
```

### Non-interactive tool IDs

- `cursor`
- `claude-code`
- `codex`
- `openclaw`
- `kilo`

### Global installation

```bash
./install --global
```

```powershell
.\install.ps1 -Global
```

### Examples

```bash
./install --directory . --tools cursor,claude-code --yes
```

```powershell
.\install.ps1 -Directory . -Tools "cursor,claude-code" -Yes
```

### Update behavior

Re-run install with the same tool selection. Installer fetches latest framework source, performs an upgrade-aware sync in `_localsetup/`, writes an upgrade report under `_localsetup/.localsetup-meta/`, then deploys platform files again.

Upgrade policy (optional):

- `--upgrade-policy preserve` (default): keep local customizations when possible.
- `--upgrade-policy force`: overwrite managed files with upstream.
- `--upgrade-policy fail-on-conflict`: abort upgrade if both local and upstream changed the same managed file.

Example:

```bash
./install --directory . --tools cursor --yes --upgrade-policy fail-on-conflict
```

</details>

## 📜 License

Localsetup is released under the [MIT License](LICENSE).

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

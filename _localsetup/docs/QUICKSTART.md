---
status: ACTIVE
version: 3.0
---

# 🚀 Quickstart

Get Localsetup v3 running in your repo in under a minute. This page covers WSL2-aware installation, platform selection, verification, and non-interactive one-liners for CI and automation.

## Prerequisites

- **Required:** `python >= 3.10`.
- **Recommended for full framework tooling:** `git >= 2.20.0`, `rg` (ripgrep), `pip`, and the Python packages in `_localsetup/requirements.txt` (PyYAML, requests, python-frontmatter, cryptography, PGPy). After install, run `python3 -m pip install -r _localsetup/requirements.txt`, or pass `--install-deps` to have the install script do it automatically.
- **Linux/macOS/WSL2:** Bash and curl.
- **Windows:** WSL2. Native PowerShell install is not supported in v3.
- **Any platform:** Network access to GitHub (or a local clone of this repo).

The installer runs a dependency preflight and prints missing dependencies with install command hints before clone/deploy. Full list: [Multi-platform install – Dependency preflight](MULTI_PLATFORM_INSTALL.md#dependency-preflight).

## Install

The v3 installer is explicit and non-interactive.

### Linux and macOS (Bash)

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash
```

```bash
./install --directory . --yes
```

Omit `--tools` or `--platforms` to install every platform in `_localsetup/config/platforms.yaml`.

## 🔧 Platform IDs

When using `--tools` or `--platforms`, use one or more of these IDs:

| ID | Agent host | Context path | Skills path | Memory file |
|----|------------|--------------|-------------|-------------|
| `cursor` | Cursor IDE | `.cursor/skills` | `~/.local/share/agents/skills/localsetup` |
| `claude-code` | Claude Code | `.claude/skills` | `~/.local/share/agents/skills/localsetup` |
| `codex` | OpenAI Codex CLI | `.codex/skills` | `~/.local/share/agents/skills/localsetup` |
| `openclaw` | OpenClaw | `.openclaw/skills` | `~/.local/share/agents/skills/localsetup` |
| `kilo` | Kilo CLI | `.kilo/skills` | `~/.local/share/agents/skills/localsetup` |
| `opencode` | OpenCode CLI | `.opencode/skills` | `~/.local/share/agents/skills/localsetup` |

You can deploy to multiple platforms at once by comma-separating: `cursor,claude-code`.

## Shared home library

V3 installs managed skills under `~/.local/share/agents/skills/localsetup` and attaches repo adapter paths to that library by symlink. Use `--mode portable` to copy managed skills into each adapter path instead.

## ✅ Verify installation

After install, run the verification scripts to confirm everything deployed correctly.

### Linux and macOS

```bash
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
```

Expected output: confirmation that context file exists and skills directory is present.

## ⚡ Non-interactive one-liners

For CI pipelines, automation, or when you already know your platform, use flags to skip prompts. Localsetup v3 installs through Bash on Linux, macOS, or WSL2.

### Linux and macOS

#### Cursor

Install into the current directory and deploy context and skills for Cursor only.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools cursor --yes
```

#### Claude Code

Install into the current directory and deploy context and skills for Claude Code only.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools claude-code --yes
```

#### Codex CLI

Install into the current directory and deploy context and skills for OpenAI Codex CLI only.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools codex --yes
```

#### OpenClaw

Install into the current directory and deploy context and skills for OpenClaw only.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools openclaw --yes
```

#### OpenCode

Install into the current directory and deploy context and skills for OpenCode CLI only.

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools opencode --yes
```

#### Kilo CLI

Install into the current directory and deploy context and skills for Kilo CLI only (local repo deploy to `.kilo/`).

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash -s -- --directory . --tools kilo --yes
```

### Windows

Localsetup v3 supports Windows through WSL2 only. Open WSL, change to the repo path, and run the Linux command:

```bash
wsl
cd /path/to/repo
./install --directory . --tools codex --yes
```

### From a local clone

If you already have the repo on disk, run from the repo root. One command per box.

#### Linux and macOS

**Cursor**

Install from a local clone into the target directory for Cursor only.

```bash
./install --directory /path/to/your/project --tools cursor --yes
```

**Claude Code**

Install from a local clone into the target directory for Claude Code only.

```bash
./install --directory /path/to/your/project --tools claude-code --yes
```

**Codex CLI**

Install from a local clone into the target directory for Codex CLI only.

```bash
./install --directory /path/to/your/project --tools codex --yes
```

**OpenClaw**

Install from a local clone into the target directory for OpenClaw only.

```bash
./install --directory /path/to/your/project --tools openclaw --yes
```

**OpenCode**

Install from a local clone into the target directory for OpenCode CLI only.

```bash
./install --directory /path/to/your/project --tools opencode --yes
```

**Kilo CLI**

Install from a local clone into the target directory for Kilo CLI only (local repo deploy to `.kilo/`).

```bash
./install --directory /path/to/your/project --tools kilo --yes
```

#### Windows

Native PowerShell install was removed for v3. Use WSL2 and run the Linux/macOS commands from inside the WSL filesystem or a mounted project path.

## 🔄 Updating

Re-run the install command with the same `--directory` and `--tools`.

```bash
./install --directory . --tools cursor --yes
```

`--upgrade-policy` is accepted for v2 compatibility; v3 uses managed install metadata and `localsetup.lock.json`.

## If dependencies are missing

If tooling reports missing **ripgrep (rg)**, install it for search-heavy workflows:

```bash
# Debian/Ubuntu
sudo apt-get install -y ripgrep
# Fedora/RHEL: sudo dnf install -y ripgrep
# Arch: sudo pacman -S --needed ripgrep
# macOS: brew install ripgrep
```

If preflight reports missing **Python/pip** or any Python modules, install and then install the framework requirements:

```bash
# Debian/Ubuntu
sudo apt-get update && sudo apt-get install -y python3 python3-pip python3-yaml

# Fedora/RHEL
sudo dnf install -y python3 python3-pip python3-pyyaml

# Arch
sudo pacman -S --needed python python-pip python-yaml

# Any: install all Python packages at once from repo root
python3 -m pip install -r _localsetup/requirements.txt
```

Alternatively, re-run install with `--install-deps` to have the script run `pip install` before applying the v3 plan.

## 📖 Next steps

- **Agent-to-agent PRD handoff (PROPOSAL):** Stamp PRDs with `python _localsetup/tools/agentq_transport_client/agentq_cli.py stamp-prd <path>`. Protocol: [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md). Client docs: `_localsetup/tools/agentq_transport_client/docs/USER_GUIDE.md`.
- [Features](FEATURES.md) - full capability list
- [Shipped skills catalog](SKILLS.md) - all shipped skills
- [Platform registry](PLATFORM_REGISTRY.md) - canonical platform definitions
- [Multi-platform install](MULTI_PLATFORM_INSTALL.md) - detailed cross-platform docs

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

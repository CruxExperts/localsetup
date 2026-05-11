---
status: ACTIVE
version: 3.1
---

# Quickstart

Use this page to install Localsetup v3, choose agent platforms, verify the install, and update later. For the product pitch, see the [root README](../../README.md).

## Requirements

- Python `>= 3.10`
- Bash on Linux, macOS, or WSL2
- Network access to GitHub, unless installing from a local clone
- Recommended: Git, `rg`, `pip`, and the packages in `_localsetup/requirements.txt`

Windows is WSL2-only in Localsetup v3. Native PowerShell install is intentionally not supported; `install.ps1` prints WSL2 guidance.

## Install In One Command

From a project root:

```bash
curl -sSL https://raw.githubusercontent.com/cptnfren/localsetup/main/install | bash
```

From a local checkout:

```bash
./install --directory . --yes
```

Install only selected agent hosts:

```bash
./install --directory . --tools codex,kilo --yes
```

If Python dependencies are missing or you want the managed venv prepared:

```bash
./install --directory . --yes --install-deps
```

Localsetup v3 does not require `--break-system-packages`.

## Platform IDs

| ID | Agent host | Adapter path | Managed package library |
|---|---|---|---|
| `cursor` | Cursor | `.cursor/skills` | `~/.local/share/agents/skills/localsetup` |
| `claude-code` | Claude Code | `.claude/skills` | `~/.local/share/agents/skills/localsetup` |
| `codex` | OpenAI Codex CLI | `.codex/skills` | `~/.local/share/agents/skills/localsetup` |
| `openclaw` | OpenClaw | `.openclaw/skills` | `~/.local/share/agents/skills/localsetup` |
| `kilo` | Kilo CLI | `.kilo/skills` | `~/.local/share/agents/skills/localsetup` |
| `opencode` | OpenCode CLI | `.opencode/skills` | `~/.local/share/agents/skills/localsetup` |

Comma-separate multiple IDs:

```bash
./install --directory . --tools cursor,claude-code,codex --yes
```

Omit `--tools` to install every platform listed in `_localsetup/config/platforms.yaml`.

## What Gets Installed

- `_localsetup/` framework source in the repo
- Managed skills under `~/.local/share/agents/skills/localsetup`
- Managed workflow packages under the same library; their source remains `_localsetup/workflows/ls-workflow-*`
- Platform adapter paths such as `.codex/skills` or `.kilo/skills`
- `localsetup.lock.json` and reports that support verification and rollback

By default, adapters point to the managed home library by symlink. Use portable mode when symlinks are not suitable:

```bash
./install --directory . --tools codex --yes --mode portable
```

## Verify

Run the core repo checks:

```bash
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
```

Read-only preflight:

```bash
python3 _localsetup/tools/localsetup_v3.py doctor
```

Agent-readable install context:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context --markdown
```

## Update

Re-run install with the same directory and platform selection:

```bash
./install --directory . --tools codex,kilo --yes
```

The installer refreshes managed skills, adapter links or portable copies, lock metadata, and reports.

Selected workflow packs also refresh their workflow packages and required capability-skill dependencies. See [Workflow packages](WORKFLOW_PACKAGES.md) for the source/runtime split.

## Roll Back Managed Paths

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . rollback
```

Rollback only acts on managed paths recorded by Localsetup metadata.

## Next Steps

- [Features](FEATURES.md)
- [Shipped skills catalog](SKILLS.md)
- [Platform registry](PLATFORM_REGISTRY.md)
- [Multi-platform install](MULTI_PLATFORM_INSTALL.md)
- [Workflow packages](WORKFLOW_PACKAGES.md)
- [Workflow registry](WORKFLOW_REGISTRY.md)

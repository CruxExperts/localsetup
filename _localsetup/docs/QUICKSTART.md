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
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash
```

From a local checkout:

```bash
./install --directory . --yes
```

This installs the default `core` pack into the managed library and does not create repo adapter paths.

Attach selected agent hosts explicitly:

```bash
./install --directory . --tools codex,kilo --yes
```

For a full local setup with all shipped skill and workflow packs attached to Codex, Kilo, and OpenCode:

```bash
./install --directory . --tools codex,kilo,opencode --packs bootstrap,core,dev,ops,integrations,publishing,experimental --install-deps --yes
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

Omit `--tools` and `--platforms` for a global-only install. No omitted selector expands to every platform.

Attach an adapter to another repo or directory while using this checkout as the source:

```bash
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor --yes
```

## What Gets Installed

- `_localsetup/` framework source in the repo
- Managed skills under `~/.local/share/agents/skills/localsetup`
- Managed workflow packages under the same library; their source remains `_localsetup/workflows/ls-workflow-*`
- Explicitly selected platform adapter paths such as `.codex/skills` or `.kilo/skills`
- `localsetup.lock.json` and reports that support verification and rollback

Selected adapters point to the managed home library by symlink. Use portable mode when symlinks are not suitable:

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

After using `--install-deps`, `doctor` verifies installed Python distributions from the managed venv interpreter, so packages whose distribution and import names differ, such as `PGPy` / `pgpy`, are reported accurately.

Agent-readable install context:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context --markdown
```

## Update

Re-run install with the same directory and platform selection:

```bash
./install --directory . --tools codex,kilo --yes
```

The installer refreshes managed skills, selected adapter links or portable copies, lock metadata, and reports. A global-only re-run refreshes the managed library and records an empty platform list.

Selected workflow packs also refresh their workflow packages and required capability skill dependencies. See [Workflow packages](WORKFLOW_PACKAGES.md) for canonical source/runtime and install details.

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

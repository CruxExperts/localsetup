---
status: ACTIVE
version: 3.8
---

# Quickstart

Use this page to install Localsetup v3, choose agent platforms, verify the install, and update later. For the product pitch, see the [root README](../../README.md).

## Requirements

- Python `>= 3.10`
- Bash on Linux, macOS, or WSL2
- Git and network access to GitHub for raw bootstrap, unless installing from a local clone
- Recommended: `rg`, `pip`, and the packages in `_localsetup/requirements.txt`; managed dependency installs use `_localsetup/requirements.lock` with pip hash checking when the lock is present.

Windows is WSL2-only in Localsetup v3. Native PowerShell install is intentionally not supported; `install.ps1` prints WSL2 guidance.

## Install In One Command

Global bootstrap from any directory:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --
```

This opens a terminal wizard. It creates or refreshes the managed source checkout, shows the source, target, managed skill library, selected platforms and packs, then asks for confirmation before applying.

The wizard uses guided choices on every step. Each prompt shows `Enter number(s) | d details | b back | q quit | ? help`; detailed mode is on by default and explains what each option does, when to choose it, and its tradeoff. Press `d` to switch to compact mode when you only want the one-line summaries.

Color and glyphs are optional presentation aids, not part of the automation contract. Interactive runs default to `--color auto --glyphs auto`, honor `NO_COLOR`, avoid color on `TERM=dumb` and non-TTY output, and fall back to text labels such as `[OK]`, `[WARN]`, and `[FAIL]` when Unicode is not appropriate. Use `--no-color`, `--color never`, or `--glyphs ascii` for portable logs.

The old public command form still opens the wizard when a terminal is available:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --yes --tools codex
```

Raw `main` bootstrap follows the current development channel. For release verification, use the GitHub release tarball and its `.sha256` sidecar, then run:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . verify-release dist/localsetup-v$(cat VERSION).tar.gz
```

Release builds also publish a CycloneDX SBOM sidecar. When it is available, include it in verification:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . verify-release \
  dist/localsetup-v$(cat VERSION).tar.gz \
  --sha256 dist/localsetup-v$(cat VERSION).tar.gz.sha256 \
  --sbom dist/localsetup-v$(cat VERSION).tar.gz.cdx.json
```

Selecting tools in the wizard, or passing `--tools` / `--platforms`, attaches adapters such as `.codex/skills` to the selected target. If no tools are selected, the install is global-library-only.

For scripts and CI, use explicit automation mode:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --non-interactive --yes
```

Automation mode keeps machine-readable output. Without a terminal and without `--non-interactive --yes`, the installer exits with a short message explaining both choices.

From a local checkout:

```bash
./install --directory .
```

The local checkout command uses that checkout as the registered source. Like the raw global bootstrap, it installs the default `core` pack into the managed library, registers `~/.local/bin/localsetup`, and does not create repo adapter paths unless you pass `--tools` or `--platforms`. If `~/.local/bin` is not on `PATH`, the installer warns and the command becomes available after you add that directory to your shell path.

After registration, run Localsetup from any project:

```bash
localsetup install --tools codex --yes
```

The global command uses the registered Localsetup checkout as source. For repo-scoped commands, it targets the nearest Git worktree root from your current directory, or the exact current directory outside Git. Override that with `--target-directory`.

Attach selected agent hosts explicitly:

```bash
localsetup install --tools codex,kilo --yes
```

For a full local setup with all shipped skill and workflow packs attached to Codex, Kilo, and OpenCode:

```bash
./install --directory . --tools codex,kilo,opencode --packs bootstrap,core,dev,ops,integrations,publishing,experimental --install-deps
```

If Python dependencies are missing or you want the managed venv prepared:

```bash
./install --directory . --install-deps
```

Localsetup v3 does not require `--break-system-packages`. Framework libraries install into a managed venv, while app-style CLI tools should use `pipx` when they are distributed as commands.

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
./install --directory . --tools cursor,claude-code,codex
```

Omit `--tools` and `--platforms` for a global-only install. No omitted selector expands to every platform.

Attach an adapter to another repo or directory while using this checkout as the source:

```bash
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor
```

Convert a repo that may already contain old Localsetup files:

```bash
localsetup convert --tools codex --packs core
localsetup convert --tools codex --packs core --yes
```

The first command is a dry report. Apply mode writes a timestamped backup and `conversion-report.json`, archives known managed or legacy Localsetup artifacts, blocks ambiguous unmanaged content, syncs the current framework source when the target is separate from the source checkout, installs selected adapters, and verifies the result.

## What Gets Installed

- `_localsetup/` framework source in the repo
- Managed skills under `~/.local/share/agents/skills/localsetup`
- Managed workflow packages under the same library; their source remains `_localsetup/workflows/ls-workflow-*`
- Explicitly selected platform adapter paths such as `.codex/skills` or `.kilo/skills`
- `localsetup.lock.json` and reports that support verification and rollback
- Transaction journals under `.localsetup/install-journal/` for applied installs

Selected adapters point to the managed home library by symlink. Use portable mode when symlinks are not suitable:

```bash
./install --directory . --tools codex --mode portable
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
localsetup doctor
```

After using `--install-deps`, `doctor` verifies installed Python distributions from the managed venv interpreter, so packages whose distribution and import names differ, such as `PGPy` / `pgpy`, are reported accurately.

Agent-readable install context:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . context --markdown
```

Verify supports explicit levels. `filesystem` runs the implemented local rule engine. `host` and `smoke` currently return structured `not_run` entries for probes that are not implemented yet, so automation can distinguish unsupported checks from failures:

```bash
localsetup verify --tools codex --level filesystem
```

Use JSONL tracing when automation needs resumable evidence:

```bash
localsetup verify --tools codex --level filesystem --trace-json /tmp/localsetup-events.jsonl
localsetup doctor --trace-json /tmp/localsetup-events.jsonl
```

Inspect planned changes against the current lockfile before applying:

```bash
localsetup diff --tools codex
```

Search the installed catalog and explain pack selection:

```bash
localsetup skill search context
localsetup skill info ls-context
localsetup workflow search audit
localsetup workflow info ls-workflow-audit-framework
localsetup why --packs core
localsetup graph
localsetup adopt --target-directory .
```

Generate SBOMs for the source tree or an installed target:

```bash
localsetup sbom --out /tmp/localsetup-source.cdx.json
localsetup sbom --installed --target-directory . --out /tmp/localsetup-installed.cdx.json
```

## Update

Re-run install with the same directory and platform selection:

```bash
./install --directory . --tools codex,kilo
```

The installer refreshes managed skills, selected adapter links or portable copies, lock metadata, and reports. A global-only re-run refreshes the managed library and records an empty platform list.

Selected workflow packs also refresh their workflow packages and required capability skill dependencies. See [Workflow packages](WORKFLOW_PACKAGES.md) for canonical source/runtime and install details.

Non-interactive strict policy blocks high-risk skill metadata unless the operator explicitly chooses a less restrictive mode:

```bash
localsetup install --tools codex --policy-mode strict --yes
```

Use `detach` when you only want to remove selected adapter paths while preserving shared managed packages and registry references:

```bash
localsetup detach --tools codex --target-directory .
```

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

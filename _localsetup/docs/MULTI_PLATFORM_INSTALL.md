---
status: ACTIVE
version: 3.8
owner_skill: ls-framework-compliance
---

# Multi-platform install (Localsetup v3)

**Purpose:** How to install Localsetup v3 for each supported AI agent platform. Supported platforms are listed in `_localsetup/config/platforms.yaml` and summarized in [_generated/platform-adapters.md](_generated/platform-adapters.md). Same framework; explicitly selected platform adapter paths point at a shared managed package library.

<p align="center">
  <img src="../../assets/localsetup-v3-install-lifecycle.svg" alt="Localsetup v3 install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

## Platform detection and script selection

- **Linux / macOS:** Use `./install`, which opens the interactive wizard by default. Automation uses `./install --non-interactive --yes`.
- **Windows:** Localsetup v3 supports Windows through WSL2 only. Native PowerShell installation surfaces are removed.
- **Git Bash (or MSYS/Cygwin) on Windows:** Open WSL2 and run the Bash installer from there.

## Install command

### Linux / macOS (Bash)

Global bootstrap from any directory:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --
```

This opens the interactive terminal wizard. It shows the source checkout, target directory, managed home library, selected platforms and packs, warnings, blockers, and planned actions before asking for final confirmation.

Every wizard prompt shows the same shortcut footer: `Enter number(s) | d details | b back | q quit | ? help`. Detailed mode is on by default, so install mode, platform, pack, adapter, and dependency choices explain what they do, when to pick them, and their tradeoffs. Press `d` to toggle compact mode; compact mode still shows one-line summaries for each option.

The visual layer remains standard-library only. `--color auto` enables ANSI color only for capable interactive terminals, while `--no-color` and `--color never` force output free of ANSI color. `--glyphs auto` uses simple Unicode status hints only on UTF-8 interactive terminals; `--glyphs ascii` keeps portable labels like `[OK]`, `[WARN]`, and `[FAIL]`. Scripted installs should continue to use `--non-interactive --yes`, which preserves machine-readable output instead of wizard screens.

The legacy public form still opens the wizard when a terminal is available:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --yes
```

Note: `sudo curl ... | bash -s --` only elevates curl; install and deploy run as the current user. For a full install as root: `curl -sSL <url> -o /tmp/install.sh && sudo bash /tmp/install.sh`.

Automation global-only install:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --non-interactive --yes
```

Automation mode creates or refreshes a managed Localsetup source checkout at `~/.local/share/localsetup/source`, installs the managed Localsetup package library, registers `~/.local/bin/localsetup`, creates no repo adapter paths unless selected, and preserves machine-readable output. If no terminal is available and `--non-interactive --yes` is not provided, the installer exits with an actionable message.

Selected platforms for the current repo after global bootstrap:

```bash
localsetup install --tools cursor,claude-code --yes
```

Or bootstrap Localsetup and attach selected adapters to the current directory in one raw command:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --tools cursor,claude-code
```

When the raw installer is run with `--tools` or `--platforms` and no explicit `--target-directory`, the wizard defaults adapters to the current directory where you launched the command. Without selected tools or platforms, the install is global-library-only.

`--tools` is a compatibility alias for the v3 `--platforms` selector.

Full local setup for the Codex, Kilo, and OpenCode adapters:

```bash
./install --directory . --tools codex,kilo,opencode --packs bootstrap,core,dev,ops,integrations,publishing,harness,experimental --install-deps
```

That command installs every declared skill and workflow pack, attaches only `.codex/skills`, `.kilo/skills`, and `.opencode/skills`, and prepares the managed `~/.local/share/localsetup/venv` dependency environment.

The `harness` pack only installs autonomous-harness capability. It does not create `HEARTBEAT.md`, `config/codex_heartbeat.yaml`, `cron/manifest.yaml`, or `.localsetup/state/codex-heartbeat/`. Activate a target repo later with `localsetup harness codex-heartbeat init` and `localsetup harness codex-heartbeat enable`; see [HARNESS_AUTOMATION.md](HARNESS_AUTOMATION.md).

Attach a selected adapter to another repo or directory:

```bash
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor
```

The managed global command separates source from target. The source is the registered Localsetup checkout recorded in `~/.local/bin/localsetup`; the target is the nearest Git worktree root from the command CWD, or the exact CWD outside Git. `--target-directory` always overrides detection.

Repo conversion uses the same target rules:

```bash
localsetup convert --tools codex --packs core
localsetup convert --tools codex --packs core --yes
```

The dry report lists artifacts and blockers. Apply mode writes `.localsetup/backups/conversion-*/conversion-report.json`, archives known managed or legacy Localsetup content, refuses ambiguous unmanaged content, removes stale target `_localsetup/` copies, installs selected adapters, and verifies.

### Windows (WSL2)

```bash
wsl
cd /path/to/repo
./install --directory .
```

## Options

- `--directory PATH` / `-Directory PATH`  - Localsetup source checkout containing `_localsetup/`. Defaults to `.` when run from a checkout; otherwise the raw Bash installer creates or refreshes `~/.local/share/localsetup/source`.
- `--target-directory PATH`  - Directory where selected repo adapter links and `.localsetup/lock.json` are written. Defaults to the source checkout for explicit local installs and to the caller's current directory for raw bootstrap installs with selected platforms.
- `--tools LIST`  - Compatibility alias for comma-separated platforms: cursor, claude-code, codex, openclaw, kilo, opencode
- `--platforms LIST`  - Space-separated v3 platform ids. Omit for a global-only install with no repo adapters.
- `--yes`  - Legacy accepted flag for interactive installs. For automation, combine with `--non-interactive`.
- `--non-interactive`  - Automation mode. Requires `--yes` and preserves machine-readable output.
- `--global`  - Removed legacy flag; v3 installs the managed home library by default and exits with an explicit error if this flag is supplied.
- `--install-deps`  - Create/update the managed `~/.local/share/localsetup/venv` and install `_localsetup/requirements.txt`
- `--no-register-shell`  - Skip creating/updating `~/.local/bin/localsetup`
- `--help`  - Print usage and exit

## Wizard choice guide

The wizard keeps the install portable and line-oriented; it uses plain terminal output with optional ANSI styling and no curses/Textual dependency. Choices can be selected by number or label, and multi-select prompts accept comma-separated values.

- **Install mode:** `Global library only` is the safest default and refreshes the shared Localsetup library without repo adapter paths. `Current directory` prepares the directory you launched from. `Another target directory` prepares a different repo while using this checkout as the source.
- **Platforms:** each selected platform shows the adapter path it writes, such as `.codex/skills` for Codex or `.cursor/skills` for Cursor.
- **Skill packs:** `core` is the suggested default for normal use. `bootstrap` adds agent-team startup and audit workflows. `dev` adds code, docs, git, test, and repo repair workflows. `ops` adds server and maintenance workflows. `integrations` adds external system connectors. `publishing` adds release and public-repo support. `harness` adds opt-in autonomous harness capability without activating it. `experimental` adds advanced or less-conservative workflows.
- **Options:** symlink adapters are easiest to update because they point repos at the managed library. Portable adapter copies are more self-contained, but updating requires copying again. Prompt-only dependency mode reports what is needed without installing dependencies. Managed virtual environment mode prepares Localsetup's managed Python environment.

## Shared home library

V3 installs managed skills and workflow packages to `~/.local/share/localsetup/packages` and writes a registry beside them. Explicitly selected repo adapter paths such as `.codex/skills` and `.kilo/skills` point at that library by symlink, or receive a managed portable copy when `--mode portable` is used.

Workflow packages are sourced from `_localsetup/workflows/ls-workflow-*`. They install beside skills because every workflow package includes a valid `SKILL.md`, while its Localsetup-specific `workflow.yaml` stays in source for validation and generated docs.

If `--tools` or `--platforms` is omitted, no repo adapter is attached. This is the safe default for refreshing the managed library without touching project-owned `.codex`, `.cursor`, `.kilo`, `.claude`, `.opencode`, or `.openclaw` configuration.

To remove a v3 install, run:

```bash
localsetup rollback
```

## Dependency preflight

Before install, use the dependency list below as the canonical source of truth. The Bash wrapper delegates preflight and dependency work to `localsetup_v3.py`; it does not call system pip directly.

### Canonical dependency list

| Dependency | Required / Recommended | Used by |
|------------|------------------------|---------|
| `git` >= 2.20.0 | Required for raw bootstrap clone and refresh; recommended otherwise | Cloning or refreshing the managed source checkout, source traceability, and release workflows |
| `rg` (ripgrep) | Recommended | Framework search and review workflows |
| `python` >= 3.10 | Required | V3 installer, framework tools, tests, and Python-first policy |
| `pip` | Recommended | Install `_localsetup/requirements.txt` inside the managed venv |
| Python: `yaml` (PyYAML>=6.0) | Recommended | YAML parsing for skill index, config, and PRD files |
| Python: `requests` (requests>=2.28) | Recommended | HTTP client used by index refresh and scrub tools |
| Python: `frontmatter` (python-frontmatter>=1.1) | Recommended | YAML frontmatter parsing for skill and PRD markdown files |
| Python: `cryptography` (cryptography>=42.0) | Recommended | Framework cryptographic primitives for secure envelope workflows |
| Python: `pgpy` (PGPy>=0.5.4,<0.6) | Recommended | Pure-Python OpenPGP support for secure mail workflows |

Python packages are listed in `_localsetup/requirements.txt`. The conservative default for Python tooling is a managed virtualenv at `~/.local/share/localsetup/venv`, which avoids PEP 668 externally managed system-pip failures. To check the current machine without changing files, run:

```bash
localsetup doctor
```

Dependency checks use installed Python distribution metadata from the selected interpreter. This keeps packages with different distribution and import names, such as `PGPy` / `pgpy`, from being misreported as missing after managed dependency installation.

To normalize install intent without changing files, run:

```bash
localsetup configure --platforms codex --packs core
```

To install dependencies automatically during install, add the `--install-deps` flag:

```bash
./install --directory . --tools cursor --install-deps
```

Without `--install-deps`, the root wrapper runs doctor in `prompt-only` mode and applies the v3 install without mutating Python dependencies. Direct Python CLI installs default to `--dependency-mode managed-venv`; use `--dependency-mode prompt-only` when you only want adapter installation.

Do not use `--break-system-packages`. If virtualenv creation is unavailable, install the OS venv package first, for example `sudo apt-get install python3-venv` on Debian/Ubuntu. Use `pipx` for standalone CLI tools, including future wheel-based Localsetup command installs; use the managed venv for libraries imported by Localsetup framework modules.

## V3 reinstall behavior

On re-run, the v3 installer refreshes the managed shared package library, rewrites the global registry, updates selected adapter links or portable copies, and writes `.localsetup/lock.json`.

`--upgrade-policy` is removed. V3 uses managed install metadata and refuses to overwrite unmanaged skill paths.

Adapter paths are conservative. The installer creates only the selected adapter subpath, for example `.cursor/skills`, and preserves neighboring project configuration such as `.cursor/rules`. It refuses unmanaged adapter directories, regular files, dangling symlinks, and symlinks that point somewhere other than the managed Localsetup library. Re-running the same install is idempotent when an adapter already points at the intended managed library or is a Localsetup-managed portable copy.

## What gets deployed

- **Shared library:** Managed skills under `~/.local/share/localsetup/packages`.
- **Workflow packages:** Managed copies of selected `_localsetup/workflows/ls-workflow-*` packages in the same library.
- **Per-platform adapters:** Explicitly selected repo paths from `_localsetup/config/platforms.yaml`, such as `.codex/skills` and `.kilo/skills`.
- **Lock and registry:** `.localsetup/lock.json` in the repo and `~/.local/share/localsetup/registry.json` in the Localsetup home.

## Framework tools

| Tool | Linux/macOS | Windows |
|------|-------------|---------|
| Install | `./install` or `localsetup install --tools codex --yes` | WSL2 only |
| Doctor | `localsetup doctor` | WSL2 only |
| Configure | `localsetup configure --platforms codex --packs core` | WSL2 only |
| Agent context | `localsetup context --markdown` | WSL2 only |
| Migrate | `localsetup migrate` | WSL2 only |
| Convert | `localsetup convert --tools codex --packs core` | WSL2 only |
| Plan | `localsetup plan --tools codex` | WSL2 only |
| Verify | `localsetup verify --tools codex` | WSL2 only |
| Tests | `./_localsetup/tests/automated_test.sh` | WSL2 only |

Framework install logic is Python-first. Shell is limited to the bootstrap wrapper, and PowerShell is not a native v3 install target.

## Repo-local

Framework source lives in the Localsetup source checkout. Target repo context and state live under `.localsetup/`, while installed skill and workflow package copies live in the managed home library. Add `--tools` or `--platforms` when you want to attach repo adapter paths.

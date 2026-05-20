---
status: ACTIVE
version: 4.0
owner_skill: ls-framework-compliance
---

# Multi-platform install (Localsetup)

**Purpose:** How to install Localsetup for each supported AI agent platform. Supported platforms are listed in `_localsetup/config/platforms.yaml` and summarized in [_generated/platform-adapters.md](_generated/platform-adapters.md). Same framework; explicitly selected platform adapter paths point at a shared managed package library.

<p align="center">
  <img src="../../assets/localsetup-install-lifecycle.svg" alt="Localsetup install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

## Platform detection and script selection

- **Linux / macOS:** Use `./install`, which opens the interactive wizard by default. Automation uses `./install --non-interactive --yes`.
- **Windows:** Localsetup supports Windows through WSL2 only. Native PowerShell installation surfaces are removed.
- **Git Bash (or MSYS/Cygwin) on Windows:** Open WSL2 and run the Bash installer from there.

## Install command

### Linux / macOS (Bash)

Global bootstrap from any directory:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --
```

This opens the interactive terminal wizard. The raw bootstrap wrapper checks the latest stable GitHub release, falls back to the latest stable-looking tag when the release API is unavailable, creates or refreshes the managed source checkout from that ref, and shows source/release status, global package-library selection, optional repo setup, selected platforms and packs, warnings, blockers, and planned actions before asking for final confirmation.

Single-choice wizard prompts show `Enter number(s) | d details | b back | q quit | ? help`. Detailed mode is on by default, so source, package-library, repo setup, and adapter choices explain what they do, when to pick them, and their tradeoffs. Multi-select prompts use checkbox controls in real terminals: move with arrows or `j`/`k`, press `Space` to toggle global packs, repo-visible packs, or platforms, and press `Enter` to accept. Scripted streams fall back to comma-separated line input. Press `d` to toggle compact mode; compact mode still shows one-line summaries for each option. Use `q` or Ctrl-C to quit; bare Esc is ignored so terminal arrow-key sequences do not cancel selection.

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

Automation mode creates or refreshes a managed Localsetup source checkout at `~/.local/share/localsetup/source` from the latest non-draft, non-prerelease GitHub release, with a stable-tag fallback when release lookup is unavailable. It installs the managed Localsetup package library, registers `~/.local/bin/localsetup`, creates no repo adapter paths unless selected, and preserves machine-readable output. If release lookup fails and a clean managed source already exists, the wrapper warns and continues from that existing source; if no managed source exists, it fails with an actionable message. If no terminal is available and `--non-interactive --yes` is not provided, the installer exits with an actionable message.

Selected platforms for the current repo after global bootstrap:

```bash
localsetup install --tools cursor,claude-code --yes
```

Or bootstrap Localsetup and attach selected adapters to the current directory in one raw command:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --tools cursor,claude-code
```

When the raw installer is run with `--tools` or `--platforms` and no explicit `--target-directory`, the wizard defaults adapters to the current directory where you launched the command. Without selected tools or platforms, the install is global-library-only.

`--tools` is a compatibility alias for the current `--platforms` selector.

Full local setup for the Codex, Kilo, and OpenCode adapters:

```bash
./install --directory . --tools codex,kilo,opencode --packs bootstrap,core,dev,ops,integrations,publishing,harness,experimental --sync-env
```

That command installs every declared skill and workflow pack, attaches only `.codex/skills`, `.kilo/skills`, and `.opencode/skills`, and syncs the uv-managed source checkout `.venv` dependency environment.

The `harness` pack only installs autonomous-harness capability. It does not create `HEARTBEAT.md`, `config/codex_heartbeat.yaml`, `cron/manifest.yaml`, or `.localsetup/state/codex-heartbeat/`. Activate a target repo later with `localsetup harness codex-heartbeat init` and `localsetup harness codex-heartbeat enable`; see [HARNESS_AUTOMATION.md](HARNESS_AUTOMATION.md).

For a smaller footprint, select by preset, taxonomy class, tag, individual skill, or exclusion:

```bash
localsetup install --tools codex --preset suggested --skill-classes development --skill-tags git --skills ls-context --exclude-skills ls-linux-patcher --yes
```

Presets are `core`, `suggested`, `all`, and `custom`. Automation defaults to `core` when no selector is supplied. Interactive installs first choose the global package-library baseline, defaulting to `core` or the prior registry setting. Repo setup is a separate choice; when selected, repo-visible packs default from the target lockfile or repo-detected suggestions. `--packs`, `--skill-classes`, `--skill-tags`, and `--skills` are additive; `--exclude-skills` removes named packages unless a selected workflow requires them. The legacy selector flags apply to both the managed global baseline and repo-visible adapter selection for compatibility. Use `--global-packs` / `--global-preset` and `--repo-packs` / `--repo-preset` when you want the managed package library to contain a broader baseline than the target repo exposes.

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
- `--platforms LIST`  - Space-separated platform ids. Omit for a global-only install with no repo adapters.
- `--preset NAME`  - Skill selection preset: core, suggested, all, or custom.
- `--packs LIST`  - Comma-separated skill/workflow packs to install.
- `--skills LIST`  - Comma-separated individual skill ids to include.
- `--skill-classes LIST`  - Comma-separated taxonomy classes to include.
- `--skill-tags LIST`  - Comma-separated taxonomy tags to include.
- `--exclude-skills LIST`  - Comma-separated individual skill ids to remove from the resolved selection unless a selected workflow requires them.
- `--global-preset NAME`, `--global-packs LIST`, `--global-skills LIST`, `--global-skill-classes LIST`, `--global-skill-tags LIST`, `--global-exclude-skills LIST`  - Selector aliases for the managed package-library baseline.
- `--repo-preset NAME`, `--repo-packs LIST`, `--repo-skills LIST`, `--repo-skill-classes LIST`, `--repo-skill-tags LIST`, `--repo-exclude-skills LIST`  - Selector aliases for packages exposed through repo adapter paths.
- `--yes`  - Legacy accepted flag for interactive installs. For automation, combine with `--non-interactive`.
- `--non-interactive`  - Automation mode. Requires `--yes` and preserves machine-readable output.
- `--global`  - Removed legacy flag; installs the managed home library by default and exits with an explicit error if this flag is supplied.
- `--sync-env`  - Sync the uv-managed source checkout `.venv` from `pyproject.toml` and `uv.lock`; quarantines corrupt Localsetup-owned legacy environments before rebuild.
- `--install-deps`  - Deprecated migration alias for `--sync-env`.
- `--install-uv` / `--no-install-uv`  - Explicitly allow or forbid uv bootstrap when `--sync-env` is requested.
- `--offline`  - Run uv dependency sync in offline/cache-only mode.
- `--no-register-shell`  - Skip creating/updating `~/.local/bin/localsetup`
- `--help`  - Print usage and exit

## Wizard choice guide

The wizard keeps the install portable and dependency-free; it uses plain terminal output with optional ANSI styling and no curses/Textual dependency. Single-choice prompts can be selected by number or label. Multi-select prompts use spacebar toggles in real terminals and comma-separated values in scripted fallback mode.

- **Source and release:** shows the source checkout, current source ref, and latest upstream release result when the raw managed bootstrap path performed a release check.
- **Global package library:** `core` is the suggested baseline for normal use. `bootstrap` adds agent-team startup and audit workflows. `dev` adds code, docs, git, test, and repo repair workflows. `ops` adds server and maintenance workflows. `integrations` adds external system connectors. `publishing` adds release and public-repo support. `harness` adds opt-in autonomous harness capability without activating it. `experimental` adds advanced or less-conservative workflows.
- **Repo setup:** `No repo setup` refreshes the managed package library without repo adapter paths. `Current directory` prepares the directory you launched from. `Another target directory` prepares a different repo while using this checkout as the source.
- **Repo adapters:** each selected platform shows the adapter path it writes, such as `.codex/skills` for Codex or `.cursor/skills` for Cursor. Repo-visible packs are selected separately from the global baseline.

## Shared home library

Localsetup installs managed skills and workflow packages to `~/.local/share/localsetup/packages` and writes a registry beside them. The managed package root contains the union of the global baseline and any repo-visible packages. Explicitly selected repo adapter paths such as `.codex/skills` and `.kilo/skills` become scoped Localsetup-managed adapter directories. In symlink mode, each selected repo-visible package inside the adapter links to the managed home library. In portable mode, the selected repo-visible packages are copied. Both modes write `.localsetup-adapter.json` so Localsetup can recognize, verify, detach, and replace the adapter later.

Workflow packages are sourced from `_localsetup/workflows/ls-workflow-*`. They install beside skills because every workflow package includes a valid `SKILL.md`, while its Localsetup-specific `workflow.yaml` stays in source for validation and generated docs.

If `--tools` or `--platforms` is omitted, no repo adapter is attached. This is the safe default for refreshing the managed library without touching project-owned `.codex`, `.cursor`, `.kilo`, `.claude`, `.opencode`, or `.openclaw` configuration.

To remove a install, run:

```bash
localsetup rollback
```

## Dependency preflight

Before install, use the dependency list below as the canonical source of truth. The Bash wrapper performs the same minimal Localsetup-owned environment quarantine needed before uv can run the Python CLI, then delegates preflight and dependency work to `localsetup.py`; it does not call system pip directly.

### Canonical dependency list

| Dependency | Required / Recommended | Used by |
|------------|------------------------|---------|
| `git` >= 2.20.0 | Required for raw bootstrap clone and refresh; recommended otherwise | Cloning or refreshing the managed source checkout, source traceability, and release workflows |
| `rg` (ripgrep) | Recommended | Framework search and review workflows |
| `python` >= 3.12 | Required | Installer, framework tools, tests, and Python-first policy |
| `uv` | Required for dependency sync | Sync `pyproject.toml` / `uv.lock` into the source checkout `.venv` |
| Python: `yaml` (PyYAML>=6.0) | Recommended | YAML parsing for skill index, config, and PRD files |
| Python: `requests` (requests>=2.28) | Recommended | HTTP client used by index refresh and scrub tools |
| Python: `frontmatter` (python-frontmatter>=1.1) | Recommended | YAML frontmatter parsing for skill and PRD markdown files |
| Python: `cryptography` (cryptography>=42.0) | Recommended | Framework cryptographic primitives for secure envelope workflows |
| Python: `pgpy` (PGPy>=0.6.0) | Recommended | Pure-Python OpenPGP support for secure mail workflows |

Python package intent is listed in `pyproject.toml`; `uv.lock` is the committed lock used by automation and installer sync. Dependency PRs must update both files when dependency intent changes. The conservative default is `prompt-only` dependency checking; explicit `--sync-env` or `--dependency-mode uv-sync` creates or updates the uv-managed source checkout `.venv` without mutating externally managed system Python. To check the current machine without changing files, run:

```bash
localsetup doctor
```

Dependency checks use installed Python distribution metadata from the selected interpreter. This keeps packages with different distribution and import names, such as `PGPy` / `pgpy`, from being misreported as missing after managed dependency installation. If `doctor` finds an old `~/.local/share/localsetup/venv` or target `.localsetup/venv` from pre-uv installs, it reports the ignored legacy venv and a repair hint instead of executing that interpreter.

To normalize install intent without changing files, run:

```bash
localsetup configure --platforms codex --packs core
```

To install dependencies automatically during install, add the `--sync-env` flag:

```bash
./install --directory . --tools cursor --sync-env
```

Without `--sync-env`, the root wrapper runs doctor in `prompt-only` mode and applies the install without syncing Python dependencies. Direct Python CLI installs use the same conservative default; pass `--dependency-mode uv-sync` when the CLI should sync the project environment before applying adapter changes.

When explicit sync is requested, Localsetup may quarantine corrupt Localsetup-owned environments by rename, never deletion. Eligible paths are the source checkout `.venv`, legacy global `~/.local/share/localsetup/venv`, and legacy target-local `.localsetup/venv`. Each quarantine writes a JSON record under Localsetup state with the original path, reason, mode, timestamp, and uv error text when applicable. A target project's own `.venv` is not Localsetup-owned and is never modified.

Do not alter system Python to satisfy Localsetup framework dependencies. Install uv or set `LOCALSETUP_UV_BIN` to a preinstalled uv binary; use `pipx` for standalone CLI tools, including future wheel-based Localsetup command installs, and use the uv project environment for libraries imported by Localsetup framework modules.

## Reinstall behavior

On re-run, the Localsetup installer refreshes the managed shared package library, rewrites the global registry, updates selected adapter links or portable copies, and writes `.localsetup/lock.json`. The wizard reloads prior global baseline selectors from the registry and repo-visible selectors, platforms, adapter mode, and dependency mode from `.localsetup/lock.json`. Choosing no repo setup for a prior target removes managed adapter state while leaving the shared package library intact.

`--upgrade-policy` is removed. Localsetup uses managed install metadata and refuses to overwrite unmanaged skill paths.

Adapter paths are conservative. The installer creates only the selected adapter subpath, for example `.cursor/skills`, and preserves neighboring project configuration such as `.cursor/rules`. It refuses unmanaged adapter directories, regular files, dangling symlinks, and symlinks that point somewhere other than the managed Localsetup library. It recognizes current scoped adapters, legacy monolithic managed symlinks, and Localsetup-managed portable copies so re-running the same install can update the adapter without exposing unrelated global packages.

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
| Tests | `uv run --locked ./_localsetup/tests/automated_test.sh` | WSL2 only |

Framework install logic is Python-first. Shell is limited to the bootstrap wrapper, and PowerShell is not a native install target.

## Repo-local

Framework source lives in the Localsetup source checkout. Target repo context and state live under `.localsetup/`, while installed skill and workflow package copies live in the managed home library. Add `--tools` or `--platforms` when you want to attach repo adapter paths.

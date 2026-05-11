---
status: ACTIVE
version: 3.1
---

# Multi-platform install (Localsetup v3)

**Purpose:** How to install Localsetup v3 for each supported AI agent platform. Supported platforms are listed in `_localsetup/config/platforms.yaml` and summarized in [_generated/platform-adapters.md](_generated/platform-adapters.md). Same framework; platform-specific adapter paths point at a shared managed package library.

<p align="center">
  <img src="../../assets/localsetup-v3-install-lifecycle.svg" alt="Localsetup v3 install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

## Platform detection and script selection

- **Linux / macOS:** Use `./install`, which delegates to `_localsetup/tools/localsetup_v3.py install --apply`.
- **Windows:** Localsetup v3 supports Windows through WSL2 only. Native PowerShell installation was removed; `install.ps1` prints WSL2 guidance and exits.
- **Git Bash (or MSYS/Cygwin) on Windows:** Open WSL2 and run the Bash installer from there.

## Install command

### Linux / macOS (Bash)

From your client repo root:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash
```

Note: `sudo curl ... | bash` only elevates curl; install and deploy run as the current user. For a full install as root: `curl -sSL <url> -o /tmp/install.sh && sudo bash /tmp/install.sh`.

Non-interactive for every platform in `_localsetup/config/platforms.yaml`:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --directory . --yes
```

Selected platforms:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --directory . --tools cursor,claude-code --yes
```

`--tools` is a compatibility alias for the v3 `--platforms` selector.

### Windows (WSL2)

```bash
wsl
cd /path/to/repo
./install --directory . --yes
```

## Options

- `--directory PATH` / `-Directory PATH`  - Client repo root (default: .)
- `--tools LIST`  - Compatibility alias for comma-separated platforms: cursor, claude-code, codex, openclaw, kilo, opencode
- `--platforms LIST`  - Space-separated v3 platform ids. Omit to install all platforms in `platforms.yaml`.
- `--yes`  - Non-interactive apply
- `--global`  - Legacy no-op compatibility flag; v3 installs the managed home library by default
- `--install-deps`  - Create/update the managed `.localsetup/venv` and install `_localsetup/requirements.txt`
- `--help`  - Print usage and exit

## Shared home library

V3 installs managed skills and workflow packages to `~/.local/share/agents/skills/localsetup` and writes a registry beside them. Repo adapter paths such as `.codex/skills` and `.kilo/skills` point at that library by symlink, or receive a managed portable copy when `--mode portable` is used.

Workflow packages are sourced from `_localsetup/workflows/ls-workflow-*`. They install beside skills because every workflow package includes a valid `SKILL.md`, while its Localsetup-specific `workflow.yaml` stays in source for validation and generated docs.

If `--tools` or `--platforms` is omitted, every platform in `platforms.yaml` is installed. Repo-local adapters take precedence because they live inside the project.

To remove a v3 install, run:

```bash
python3 _localsetup/tools/localsetup_v3.py rollback
```

## Dependency preflight

Before install, use the dependency list below as the canonical source of truth. The Bash wrapper delegates preflight and dependency work to `localsetup_v3.py`; it does not call system pip directly.

### Canonical dependency list

| Dependency | Required / Recommended | Used by |
|------------|------------------------|---------|
| `git` >= 2.20.0 | Recommended | Source traceability and release workflows |
| `rg` (ripgrep) | Recommended | Framework search and review workflows |
| `python` >= 3.10 | Required | V3 installer, framework tools, tests, and Python-first policy |
| `pip` | Recommended | Install `_localsetup/requirements.txt` inside the managed venv |
| Python: `yaml` (PyYAML>=6.0) | Recommended | YAML parsing for skill index, config, and PRD files |
| Python: `requests` (requests>=2.28) | Recommended | HTTP client used by index refresh and scrub tools |
| Python: `frontmatter` (python-frontmatter>=1.1) | Recommended | YAML frontmatter parsing for skill and PRD markdown files |
| Python: `cryptography` (cryptography>=42.0) | Recommended | Framework cryptographic primitives for secure envelope workflows |
| Python: `pgpy` (PGPy>=0.6.0) | Recommended | Pure-Python OpenPGP support for secure mail workflows |

Python packages are listed in `_localsetup/requirements.txt`. The conservative default for Python tooling is a managed virtualenv at `.localsetup/venv`, which avoids PEP 668 externally managed system-pip failures. To check the current machine without changing files, run:

```bash
python3 _localsetup/tools/localsetup_v3.py doctor
```

To normalize install intent without changing files, run:

```bash
python3 _localsetup/tools/localsetup_v3.py configure --platforms codex --packs core
```

To install dependencies automatically during install, add the `--install-deps` flag:

```bash
./install --directory . --tools cursor --yes --install-deps
```

Without `--install-deps`, the root wrapper runs doctor in `prompt-only` mode and applies the v3 install without mutating Python dependencies. Direct Python CLI installs default to `--dependency-mode managed-venv`; use `--dependency-mode prompt-only` when you only want adapter installation.

Do not use `--break-system-packages`. If virtualenv creation is unavailable, install the OS venv package first, for example `sudo apt-get install python3-venv` on Debian/Ubuntu.

## V3 reinstall behavior

On re-run, the v3 installer refreshes the managed shared package library, rewrites the global registry, updates selected adapter links or portable copies, and writes `localsetup.lock.json`.

`--upgrade-policy` is accepted by the root wrapper as a legacy compatibility flag, but v3 uses managed install metadata and refuses to overwrite unmanaged skill paths.

## What gets deployed

- **Shared library:** Managed skills under `~/.local/share/agents/skills/localsetup`.
- **Workflow packages:** Managed copies of selected `_localsetup/workflows/ls-workflow-*` packages in the same library.
- **Per-platform adapters:** Repo paths from `_localsetup/config/platforms.yaml`, such as `.codex/skills` and `.kilo/skills`.
- **Lock and registry:** `localsetup.lock.json` in the repo and `.localsetup-registry.json` in the managed home library.

## Framework tools

| Tool | Linux/macOS | Windows |
|------|-------------|---------|
| Install | `./install` or `python3 _localsetup/tools/localsetup_v3.py install --apply` | WSL2 only |
| Doctor | `python3 _localsetup/tools/localsetup_v3.py doctor` | WSL2 only |
| Configure | `python3 _localsetup/tools/localsetup_v3.py configure` | WSL2 only |
| Agent context | `python3 _localsetup/tools/localsetup_v3.py context --markdown` | WSL2 only |
| Migrate | `python3 _localsetup/tools/localsetup_v3.py migrate` | WSL2 only |
| Plan | `python3 _localsetup/tools/localsetup_v3.py plan` | WSL2 only |
| Verify | `python3 _localsetup/tools/localsetup_v3.py verify` | WSL2 only |
| Tests | `./_localsetup/tests/automated_test.sh` | WSL2 only |

Framework install logic is Python-first. Shell is limited to the bootstrap wrapper, and PowerShell is not a native v3 install target.

## Repo-local

Framework source and repo-local context live in the repo. Installed skill and workflow package copies live in the managed home library and can be recreated from the repo with `./install --directory . --yes`.

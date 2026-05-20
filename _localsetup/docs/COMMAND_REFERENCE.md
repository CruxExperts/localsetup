---
status: ACTIVE
version: 4.0
owner_skill: ls-framework-compliance
---

# Command Reference

Use this page when you need copy-pasteable Localsetup commands. For narrative install guidance, start with [Quickstart](QUICKSTART.md) or [Multi-platform install](MULTI_PLATFORM_INSTALL.md).

## Bootstrap Installer

The public Bash wrapper is the entry point for Linux, macOS, and WSL2. Windows support is WSL2-only.

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s --
```

Run the same wrapper in automation mode:

```bash
curl -sSL https://raw.githubusercontent.com/CruxExperts/localsetup/main/install | bash -s -- --non-interactive --yes
```

Install from a local checkout:

```bash
./install --directory .
```

Attach selected platform adapters to the target repo:

```bash
./install --directory . --tools codex,kilo
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor
```

`--tools` is the compatibility alias for `--platforms`. If both are omitted, Localsetup refreshes the managed package library only and does not create repo adapter paths.

## Installer Options

| Option | Meaning |
|---|---|
| `--directory PATH` | Localsetup source checkout containing `_localsetup/`. Without an explicit checkout, the raw bootstrap creates or refreshes `~/.local/share/localsetup/source`. |
| `--target-directory PATH` | Repo or directory where selected adapter paths and `.localsetup/lock.json` are written. |
| `--home PATH` | Home directory for the managed source and package library. Defaults to `$HOME`. |
| `--yes` | Accepted legacy flag. For automation, combine with `--non-interactive`. |
| `--non-interactive` | Automation mode. Requires `--yes` and preserves machine-readable output. |
| `--tools LIST` | Comma-separated platform ids. Alias for `--platforms`. |
| `--platforms LIST` | Platform adapter ids. Omit for global-library-only install. |
| `--preset NAME` | Selection preset: `core`, `suggested`, `all`, or `custom`. |
| `--packs LIST` | Comma-separated skill and workflow packs. |
| `--skills LIST` | Comma-separated individual skill ids. |
| `--skill-classes LIST` | Comma-separated taxonomy classes. |
| `--skill-tags LIST` | Comma-separated taxonomy tags. |
| `--exclude-skills LIST` | Skills to remove unless required by a selected workflow. |
| `--global-*` | Selection options for the managed package-library baseline. |
| `--repo-*` | Selection options for packages exposed through repo adapter paths. |
| `--mode symlink\|portable` | Adapter write mode. Symlink is the default; portable copies selected packages. |
| `--sync-env` | Sync the uv-managed source checkout environment from `pyproject.toml` and `uv.lock`. |
| `--install-deps` | Deprecated alias for `--sync-env`. |
| `--install-uv` / `--no-install-uv` | Allow or forbid uv bootstrap when sync is requested. |
| `--offline` | Run uv sync in offline/cache-only mode. |
| `--no-register-shell` | Skip `~/.local/bin/localsetup` registration. |
| `--color auto\|always\|never` | Wizard color mode. |
| `--no-color` | Alias for `--color never`. |
| `--glyphs auto\|ascii\|unicode` | Wizard glyph mode. |
| `--help` / `-h` | Print installer help. |

## Managed CLI

After registration, `localsetup` uses the registered framework source and targets the nearest Git worktree root from the current directory unless `--target-directory` is supplied.

```bash
localsetup install --tools codex --yes
localsetup verify --tools codex --level filesystem
localsetup doctor
localsetup diff --tools codex
localsetup rollback
```

From this source checkout, run the CLI through uv:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . generate-docs
uv run --locked python _localsetup/tools/localsetup.py --source-root . docs-align check --ci
```

## CLI Commands

The top-level CLI currently exposes these commands:

```text
plan, install, verify, rollback, update, adapters, configure, doctor,
migrate, context, convert, catalog, diff, skill, workflow, why, graph,
adopt, detach, sbom, scan-migration, audit-global-first, validate-catalog,
generate-docs, provenance, harness, docs-align, context-index, hook-gate,
version-plan, version-sync, release-push, self-refresh, install-hooks,
register-shell, wizard, package, verify-release
```

Most commands emit JSON by default. Commands with explicit human-readable modes, such as `context --markdown`, document that mode in their own help.

## Install Command Options

The Python CLI install command supports the same selection model as the wrapper:

```bash
localsetup install \
  --tools codex \
  --preset suggested \
  --skill-classes development \
  --skill-tags git \
  --skills ls-context \
  --exclude-skills ls-linux-patcher \
  --yes
```

Useful install options:

| Option | Meaning |
|---|---|
| `--config PATH` | Load install config. |
| `--target-directory PATH` | Override target directory. |
| `--json` | Make JSON output explicit. |
| `--report PATH` | Write an install report. |
| `--backup-dir PATH` | Use an explicit backup location. |
| `--trace-json PATH` | Append JSONL trace events. |
| `--policy-mode permissive\|standard\|strict\|ci` | Choose policy strictness. |
| `--dependency-mode managed-venv\|prompt-only\|user-pip\|uv-sync` | Choose dependency handling. |
| `--apply` | Apply a planned operation when the command supports plan/apply separation. |
| `--mode symlink\|portable` | Adapter write mode. |
| `--platforms ...` / `--tools ...` | Platform adapter ids. |

## Maintainer Commands

Run these from the repository root when changing docs, catalogs, release metadata, skills, workflows, or platform manifests:

```bash
uv run --locked python _localsetup/tools/docs_alignment.py --repo-root . inventory
uv run --locked python _localsetup/tools/docs_alignment.py --repo-root . check --ci
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup.py --source-root . generate-docs
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked ./_localsetup/tests/automated_test.sh
uv run --locked pytest -n auto _localsetup/tests -q
git diff --check
```

Use `release-push` only when the release wave explicitly includes publishing:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . release-push
```

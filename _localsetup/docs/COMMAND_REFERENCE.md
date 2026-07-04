---
status: ACTIVE
version: 4.2
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

`--tools` is the compatibility alias for `--platforms`. If both are omitted on a source-only install, Localsetup refreshes the managed package library only and does not create repo adapter paths. If a repo target is explicit, selector-free `plan`, `install --apply`, and `update` use auto mode:

```bash
localsetup plan --target-directory .
localsetup install --target-directory . --apply
localsetup update --target-directory .
```

Auto mode infers existing Localsetup state, applies only unambiguous safe repairs, or installs the `normal` global baseline for a brand-new repo without adapter paths.

## Installer Options

| Option | Meaning |
|---|---|
| `--directory PATH` | Localsetup source checkout containing `_localsetup/`. Without an explicit checkout, the raw bootstrap creates or refreshes `~/.local/share/localsetup/source`. |
| `--target-directory PATH` | Repo or directory where selected adapter paths and `.localsetup/lock.json` are written; without selector flags on `plan`, `install --apply`, and `update`, enables auto mode. |
| `--home PATH` | Home directory for the managed source and package library. Defaults to `$HOME`. |
| `--yes` | Accepted legacy flag. For automation, combine with `--non-interactive`. |
| `--non-interactive` | Automation mode. Requires `--yes` and preserves machine-readable output. |
| `--tools LIST` | Comma-separated platform ids. Alias for `--platforms`. |
| `--platforms LIST` | Platform adapter ids. Explicit values override auto mode. |
| `--preset NAME` | Selection preset: `core`, `normal`, `suggested`, `all`, or `custom`. |
| `--packs LIST` | Comma-separated skill and workflow packs. |
| `--skills LIST` | Comma-separated individual skill ids. |
| `--workflows LIST` | Comma-separated workflow package ids or workflow aliases. |
| `--skill-classes LIST` | Comma-separated taxonomy classes. |
| `--skill-tags LIST` | Comma-separated taxonomy tags. |
| `--exclude-skills LIST` | Skills to remove unless required by a selected workflow. |
| `--global-*` | Selection options for the managed package-library baseline, including `--global-workflows`. |
| `--repo-*` | Selection options for packages exposed through repo adapter paths, including `--repo-workflows`. |
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
localsetup adapters check --tools codex
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
candidate-skill, adopt, detach, sbom, scan-migration, audit-global-first,
validate-catalog, generate-docs, provenance, harness, docs-align, context-index, hook-gate,
version-plan, version-sync, release-push, self-refresh, install-hooks,
register-shell, wizard, package, verify-release
```

`candidate-skill validate --candidate <path> --json` and `candidate-skill proposal --candidate <path> --output -` inspect repo-scoped candidate skills without promoting them into managed packages or adapter directories.

`wizard --repo-profile universal-agent-repo --target-directory <path> --dry-run --report <path>` plans the lean universal agent repository shape without entering the interactive installer. Re-run with `--apply` to create the missing shape files. Existing files with different content are blockers; Localsetup does not overwrite them.

Most commands emit JSON by default. Commands with explicit human-readable modes, such as `context --markdown`, document that mode in their own help.

`localsetup adapters` preserves the legacy adapter status list output. Use `localsetup adapters check --tools codex` for a structured, report-only adapter compatibility payload with `ok`, `adapters`, `issues`, `warnings`, `repair_hints`, `summary`, and suggested existing commands. It exits `0` when the adapter check is OK and `1` when verifier issues are present.

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

## Repair And Health Commands

`doctor repair` is report-only by default. It infers platforms, adapter mode, repo-visible skills, repo-visible workflows, custom repo skills, and stale framework state, then returns a JSON report with `repair_schema_version: 2`.

```bash
localsetup doctor repair --target-directory .
localsetup doctor repair --target-directory . --repair-mode migration-plan --agent-prompt
localsetup doctor repair --target-directory . --repair-mode migration-plan --emit-agent-prompt /tmp/localsetup-repair.md
localsetup doctor repair --target-directory . --repair-mode safe-repair --yes
localsetup doctor repair --target-directory . --repair-mode apply-with-backups --yes
```

Safe repair only mutates Localsetup-owned state. It can back up and remove a legacy `_localsetup/` tree only when the target tree is framework-shaped and matches the current source framework contents byte-for-byte. Clean tracked framework trees are backed up, untracked with `git rm -r --cached -- _localsetup`, and then removed from the working tree. Protected source checkouts, symlinks, dirty trees, framework-shaped trees with extra or modified files, and custom `_localsetup/` content are preserved and reported as decisions for migration planning.

Custom repo skills are repo-owned by default. Adapter directories such as `.codex/skills`, `.claude/skills`, `.cursor/skills`, `.kilo/skills`, `.openclaw/skills`, `.opencode/skills`, and historical `.agents/skills` are shared agent surfaces, not exclusive Localsetup-owned directories. Mixed adapter directories are repaired in place when selected Localsetup-managed entries are safe to update. Same-name collisions are reported as decisions or blockers, and custom entries remain preserved in place until the repo owner explicitly chooses a migration or remediation path. See [Adapter ownership](ADAPTER_OWNERSHIP.md).

Health commands surface blocked repairs and handoff prompts:

```bash
localsetup health --json
localsetup health repair-queue --json
localsetup health repair-queue --agent-prompts /tmp/localsetup-prompts
```

`.localsetup/lock.json` is intentional managed repo state and remains visible to Git. Runtime summaries and journals are locally excluded through `.git/info/exclude`: `.localsetup/health.json`, `.localsetup/AGENT_STATUS.md`, `.localsetup/install-journal/`, `.localsetup/backups/`, `.localsetup/state/`, and `.localsetup/context-index/`.

## Resolver And Validation Commands

Use resolver commands when scripts, docs, workflows, or agents need directly followable Localsetup paths:

```bash
localsetup path --json
localsetup path source-root
localsetup path framework-root
localsetup path docs-root
localsetup path tools-root
localsetup path package-root
localsetup path package ls-context SKILL.md
localsetup path doc WORKFLOW_REGISTRY.md
localsetup path tool tmux_ops
```

`localsetup path --json` refreshes `paths.json` under the configured Localsetup home. Named path commands print one absolute path.

Use package-surface validation after changing skills, workflows, resolver tokens, materialization rules, or deployed path contracts:

```bash
localsetup validate-package-surface
localsetup validate-catalog
```

Use `reprocess-paths` for whole-project path-contract reporting. Apply mode is intentionally disabled until allowlisted rewrites are implemented:

```bash
localsetup reprocess-paths
```

Use `test-workers` to compute the default full-suite pytest worker count:

```bash
localsetup test-workers
localsetup test-workers --json
localsetup test-workers --workers 4
```

The default is `ceil(available CPU cores / 2)`, clamped to `1..255`. `LOCALSETUP_TEST_WORKERS` or `--workers` can override the value; non-integer overrides fail with an explicit configuration error.

## Maintainer Commands

Run these from the repository root when changing docs, catalogs, release metadata, skills, workflows, or platform manifests:

```bash
uv run --locked python _localsetup/tools/docs_alignment.py --repo-root . inventory
uv run --locked python _localsetup/tools/docs_alignment.py --repo-root . check --ci
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup.py --source-root . generate-docs
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-package-surface
uv run --locked ./_localsetup/tests/automated_test.sh
workers="$(uv run --locked python _localsetup/tools/localsetup.py --source-root . test-workers)"
uv run --locked pytest -n "$workers" _localsetup/tests -q
git diff --check
```

Run focused pytest targets and matching Localsetup validators before broad suites. Reserve the full Python suite for final consolidation on broad/shared runtime changes, release or publish work, dependency changes, or explicit maintainer requests. `test-workers` computes `ceil(available CPU cores / 2)` and clamps overrides into `1..255`.

Use `release-push` only when the release wave explicitly includes publishing:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . release-push
```

For release preparation without pushing, run `publish-preflight --base origin/main --head HEAD --fix` first; it creates the required version-sync/generated-doc commit before the guarded push.

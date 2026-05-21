# Localsetup Framework Engine

**Version:** 4.0.9<br>

`_localsetup/` is the engine that makes the public Localsetup promise real. It stores the framework code, shipped skills, workflow packages, platform templates, docs, tests, and install manifests that turn a repository into a portable agent workspace.

For the public product overview, start with the [root README](../README.md). This page is the contributor and maintainer map for the framework internals.

<p align="center">
  <img src="../assets/localsetup-architecture.svg" alt="Localsetup architecture: repo source, config resolver, managed home library, adapters, and rollback metadata" width="960">
</p>

## What this directory owns

- **Framework source:** Python tooling, shared libraries, templates, config manifests, tests, docs, shipped skills, and workflow packages.
- **Skill source of truth:** Every shipped capability skill lives under `skills/ls-*` as an Agent Skills-compatible `SKILL.md` package.
- **Workflow source of truth:** Every first-class workflow package lives under `workflows/ls-workflow-*` with `SKILL.md` plus Localsetup `workflow.yaml` metadata.
- **Platform adapters:** Templates and manifests define how explicitly selected agent hosts attach to the managed Localsetup package library.
- **Public docs:** `docs/` explains install behavior, platform support, workflow registries, skill import, Agent Q transport, versioning, and release validation.
- **Verification:** The Localsetup CLI and framework audit tools validate catalog shape, generated docs, migration state, and release readiness.

Generated adapter folders in consuming repositories are install output. Do not treat them as framework source.

## Install flow

<p align="center">
  <img src="../assets/localsetup-install-lifecycle.svg" alt="Localsetup install lifecycle: doctor, configure, context, plan, install, verify, ship, and rollback" width="960">
</p>

The root Bash installer delegates to the Python CLI. The CLI resolves platform intent, creates or refreshes the managed home package library, attaches only explicitly selected repo adapter paths, writes lock/report metadata, and supports rollback for managed paths.

Common commands from the repository root:

```bash
./install --directory .
./install --directory . --tools codex,kilo
./install --directory /path/to/localsetup --target-directory /path/to/project --tools cursor
./install --directory . --tools codex --non-interactive --yes
uv run --locked python _localsetup/tools/localsetup.py doctor
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . rollback
```

The root wrapper opens the interactive wizard by default. Automation must use `--non-interactive --yes`.

Use WSL2 for Windows. Native PowerShell installation is intentionally not supported in the current framework.

## Directory map

| Path | Purpose |
|---|---|
| `config/` | Platform manifests, pack lists, and default framework configuration. |
| `discovery/` | OS discovery helpers and compatibility launchers. |
| `docs/` | Public framework docs shipped with the repo. |
| `lib/` | Shared shell and helper library code. |
| `skills/` | Source packages for all shipped `ls-*` skills. |
| `templates/` | Platform-specific context loaders and adapter templates. |
| `tests/` | Bash and pytest coverage for framework behavior. |
| `tools/` | Localsetup CLI, docs generation, validation, release, skill index, and Agent Q tooling. |
| `core/` | Planner, apply, verify, rollback, versioning, and CLI implementation modules. |
| `workflows/` | Source packages for all shipped `ls-workflow-*` workflow packages. |

## Supported platforms

The canonical list lives in [docs/PLATFORM_REGISTRY.md](docs/PLATFORM_REGISTRY.md). Current platform IDs are:

- `cursor`
- `claude-code`
- `codex`
- `openclaw`
- `kilo`
- `opencode`

Omitting `--tools` or `--platforms` installs the managed library only. Use `--tools` or `--platforms` to attach the selected repo adapter paths.

## Skill model

Skills are task-focused instruction packages. Localsetup keeps the canonical source under `_localsetup/skills/` in the source checkout, installs managed copies to `~/.local/share/localsetup/packages`, and attaches selected platform adapter paths to that library by symlink or portable copy.

Useful docs:

- [Shipped skills catalog](docs/SKILLS.md)
- [Agent Skills compliance](docs/AGENT_SKILLS_COMPLIANCE.md)
- [Skill importing](docs/SKILL_IMPORTING.md)
- [Skill interoperability](docs/SKILL_INTEROPERABILITY.md)
- [Skill normalization](docs/SKILL_NORMALIZATION.md)

## Workflow package model

Workflow packages are executable orchestration packages. They live under `_localsetup/workflows/ls-workflow-*`, include a valid Agent Skills `SKILL.md`, and add a Localsetup `workflow.yaml` manifest. The manifest is the source for workflow IDs, aliases, required skills, gates, phases, validation, outputs, and generated registry rows.

The install planner selects workflows from `_localsetup/config/pack.yaml`, installs them beside skills in the managed home library, and auto-includes required capability skills. Generated workflow docs should come from manifests, not hand-edited tables.

Useful docs:

- [Workflow packages guide](docs/WORKFLOW_PACKAGES.md)
- [Workflow package standard](docs/WORKFLOW_STANDARD.md)
- [Workflow registry](docs/WORKFLOW_REGISTRY.md)
- [Workflow quick reference](docs/WORKFLOW_QUICK_REF.md)

## Maintenance checks

Run these before release-oriented changes:

```bash
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . scan-migration
uv run --locked python _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/localsetup-framework-audit.md
uv run --locked pytest -n auto _localsetup/tests -q
git diff --check
```

For the full version and release flow, see [docs/VERSIONING.md](docs/VERSIONING.md).

## Public docs

Start here:

- [Docs index](docs/README.md)
- [Quickstart](docs/QUICKSTART.md)
- [Command reference](docs/COMMAND_REFERENCE.md)
- [Features](docs/FEATURES.md)
- [Platform registry](docs/PLATFORM_REGISTRY.md)
- [Workflow registry](docs/WORKFLOW_REGISTRY.md)
- [Security policy](../SECURITY.md)
- [Contributing guide](../CONTRIBUTING.md)

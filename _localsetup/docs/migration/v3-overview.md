---
status: ACTIVE
version: 3.7
---

# Localsetup v3 Overview

Localsetup v3 installs one global package library for skills and workflow packages, then attaches repositories to it.

## Global Library

Default global path:

- `~/.local/share/agents/skills/localsetup/`

The global library contains managed copies of selected capability skills and selected workflow packages. Source stays split:

- Skills: `_localsetup/skills/ls-*`
- Workflow packages: `_localsetup/workflows/ls-workflow-*`

Repo attachment lockfile:

- `localsetup.lock.json`

## Windows Support

Windows support is WSL2-only in v3. Run agents inside WSL and use WSL filesystem paths.

## Core Commands

- `python3 _localsetup/tools/localsetup_v3.py plan`
- `python3 _localsetup/tools/localsetup_v3.py doctor`
- `python3 _localsetup/tools/localsetup_v3.py configure`
- `python3 _localsetup/tools/localsetup_v3.py context --markdown`
- `python3 _localsetup/tools/localsetup_v3.py migrate`
- `python3 _localsetup/tools/localsetup_v3.py install --apply`
- `python3 _localsetup/tools/localsetup_v3.py verify`
- `python3 _localsetup/tools/localsetup_v3.py rollback`
- `python3 _localsetup/tools/localsetup_v3.py adapters`
- `python3 _localsetup/tools/localsetup_v3.py catalog`
- `python3 _localsetup/tools/localsetup_v3.py validate-catalog`
- `python3 _localsetup/tools/localsetup_v3.py scan-migration`
- `python3 _localsetup/tools/localsetup_v3.py hook-gate`
- `python3 _localsetup/tools/localsetup_v3.py generate-docs`
- `python3 _localsetup/tools/localsetup_v3.py package --out dist/localsetup-v3-public.tar.gz`

## Platform Adapters

The adapter contract is generated from `_localsetup/config/platforms.yaml`.
Each selected platform gets a repo-local attachment path that points at the
shared global library. Omitting platform selectors is global-only and creates no
repo adapters. Verification without an explicit selector checks the recorded
install state rather than assuming every declared platform was attached.

## Portable Mode

Portable mode vendors managed copies into the repo adapter paths:

- `python3 _localsetup/tools/localsetup_v3.py install --mode portable --platforms codex --apply`

Use portable mode for repos that must carry their selected packages without relying on
the user's global library.

## Packs And Migration

The pack contract lives in `_localsetup/config/pack.yaml`. The default install
uses `core`; optional packs can be requested with `--packs`.

Pack entries can select both skills and workflow packages. Workflow packages are listed under `workflow_packs` and may auto-include required capability skills through their `workflow.yaml` manifests.

Migration scanning reports remaining `localsetup-*` references outside the
source skill corpus so maintainers can decide whether each reference should stay
as historical documentation or move to the v3 `ls-*` name.

In the source-only v3 tree, expected remaining scan findings are limited to
generated alias metadata and the v2-to-v3 skill map. Those entries are
intentional historical references used by migration reports and compatibility
docs; new source skills and user-facing setup docs should use `ls-*` names.

`migrate` is conservative: it backs up first, renames only known managed
`localsetup-*` global skill artifacts through the v2-to-v3 alias map, and
refuses unmanaged adapter collisions with remediation commands in the report.

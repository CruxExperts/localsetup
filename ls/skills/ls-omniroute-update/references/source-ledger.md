# OmniRoute Source Ledger

## Upstream

- Repository: `https://github.com/diegosouzapw/OmniRoute`
- Skills root: `skills/`
- Current Localsetup source version: `v3.8.48`
- Annotated tag object: `4f00f84b5a12f90fca2f1d72a60404cf6f5bf059`
- Current Localsetup source commit: `7ee5bbc64dbb03e967521227f2afffeb7c9dad1e`
- Current Localsetup source tree: `4048504f76c6fb3dedd00ff2aa7250109308de99`
- Current Localsetup skills tree: `e7b1871e0904fbdb0ff01bdc3fc1d7ea599707ff`
- Current Localsetup source commit date: `2026-07-13T21:18:54Z`
- Upstream package version: `3.8.48`
- npm `latest` at authorization: `3.8.48`
- Release/package commit: `7ee5bbc64dbb03e967521227f2afffeb7c9dad1e` for tag/npm `v3.8.48`

## Source Priority

1. A local OmniRoute checkout supplied with `--source-path`, when the operator knows it is the intended source.
2. The upstream Git repository at a pinned commit, tag, or branch supplied with `--ref`.
3. The upstream default branch only for discovery reports, never for final provenance.

## Refresh Rules

- Refresh this ledger before importing, updating, consolidating, or removing any OmniRoute skill coverage.
- Prefer a pinned commit for conversion or coverage metadata.
- Record the commit SHA, commit date, source path, source SHA-256 when applicable, and access date for every converted skill or native coverage wave.
- Treat the actual `skills/*/SKILL.md` inventory as authoritative. For `v3.8.48`, the pinned tree contains 44 skills, including `omni-github-skills`.
- If upstream disappears or a skill is renamed, classify the local coverage as `local-only` or `missing-local` until a maintainer confirms removal or migration.

## Four-Skill Native Pack

Localsetup intentionally consolidates OmniRoute `v3.8.48` into four native skills instead of shipping one Localsetup skill per upstream skill document.

Current native pack:

- `ls-omniroute` with `local_role: main-router`
- `ls-omniroute-proxy` with `local_role: proxy-discovery`
- `ls-omniroute-admin-automation` with `local_role: admin-automation`
- `ls-omniroute-update` with `local_role: update-workflow`

Authoritative coverage map:

- Human-readable: `../../ls-omniroute/references/upstream-skill-coverage.md`
- Machine-readable: `../scripts/omniroute_update.py` `NATIVE_COVERAGE`

Immutable source inventory:

- Extractor: `../scripts/omniroute_inventory.py`
- Inputs: the exact pinned Git object, its `skills/*/SKILL.md` blobs, and `docs/openapi.yaml`
- Outputs: full skill, OpenAPI endpoint, and `omniroute_*` tool inventories with canonical SHA-256 digests
- The extractor reads Git objects only and does not emit the local mirror path.

Strict coverage acceptance for `v3.8.48` is:

- 44 upstream skills discovered from the pinned source tree.
- 44 upstream skills reported as `covered-native` or `current`.
- No `missing-local`, `stale-local`, `local-only`, or untracked converted package blockers under strict flags.

## Current Boundary

The bundled updater is report-first. It produces comparison, coverage, and freshness reports and does not automatically write, remove, or replace converted skill directories.

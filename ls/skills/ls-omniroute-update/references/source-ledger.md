# OmniRoute Source Ledger

## Upstream

- Repository: `https://github.com/diegosouzapw/OmniRoute`
- Skills root: `skills/`
- Current Localsetup source version: `v3.8.43`
- Current Localsetup source commit: `0c7f756f922fe3c0408e41852577027b496489bf`
- Current Localsetup source commit date: `2026-07-03T21:16:16Z`
- Upstream package version: `3.8.43`
- npm `latest`: `3.8.43`
- Release/package commit: `b729a8f27364f072c87082e03bb8e122f3d76251` for tag/npm `v3.8.43`
- Checked date: 2026-07-04

## Source Priority

1. A local OmniRoute checkout supplied with `--source-path`, when the operator knows it is the intended source.
2. The upstream Git repository at a pinned commit, tag, or branch supplied with `--ref`.
3. The upstream default branch only for discovery reports, never for final provenance.

## Refresh Rules

- Refresh this ledger before importing, updating, consolidating, or removing any OmniRoute skill coverage.
- Prefer a pinned commit for conversion or coverage metadata.
- Record the commit SHA, commit date, source path, source SHA-256 when applicable, and access date for every converted skill or native coverage wave.
- Treat the actual `skills/*/SKILL.md` inventory as authoritative when upstream prose has stale count text. For `v3.8.43`, the actual inventory is 43 skills even though two upstream docs still mention a 42-skill catalog.
- If upstream disappears or a skill is renamed, classify the local coverage as `local-only` or `missing-local` until a maintainer confirms removal or migration.

## 2026-07-04 Consolidated Native Pack

Localsetup intentionally consolidates OmniRoute `v3.8.43` into a small native skill pack instead of shipping one Localsetup skill per upstream skill document.

Current native pack:

- `ls-omniroute` with `local_role: main-router`
- `ls-omniroute-proxy` with `local_role: proxy-discovery`
- `ls-omniroute-admin-automation` with `local_role: admin-automation`
- `ls-omniroute-observability` with `local_role: observability`
- `ls-omniroute-context` with `local_role: context-compression`
- `ls-omniroute-integrations` with `local_role: integrations`
- `ls-omniroute-codex` with `local_role: codex-onboarding`
- `ls-omniroute-update` with `local_role: update-workflow`

Authoritative coverage map:

- Human-readable: `../ls-omniroute/references/upstream-skill-coverage.md`
- Machine-readable: `../ls-omniroute-update/scripts/omniroute_update.py` `NATIVE_COVERAGE`

Strict coverage acceptance for `v3.8.43` is:

- 43 upstream skills discovered from the pinned source tree.
- 43 upstream skills reported as `covered-native` or `current`.
- No `missing-local`, `stale-local`, `local-only`, or untracked converted package blockers under strict flags.

## Historical Note

The 2026-05-24 import wave converted 18 older upstream skills from commit `89aa761e667b38e25eb044e69b524e90de99cbe9`.

The first 2026-06-21 strict-replace pass mapped all 43 upstream skills to one-to-one Localsetup names such as `ls-cli-chat`, `ls-omni-auth`, and `ls-config-codex-cli`. That proved the source inventory and provenance, but the final user-facing pack was consolidated into the native skill set above to keep agent context smaller and easier to route.

## Current Boundary

The bundled updater is report-first. It produces comparison, coverage, and freshness reports and does not automatically write, remove, or replace converted skill directories.

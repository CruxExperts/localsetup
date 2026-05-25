# OmniRoute Source Ledger

## Upstream

- Repository: `https://github.com/diegosouzapw/OmniRoute`
- Skills root: `skills/`
- Planning-time checked branch head: `89aa761e667b38e25eb044e69b524e90de99cbe9`
- Import-wave pinned commit: `89aa761e667b38e25eb044e69b524e90de99cbe9`
- Import-wave commit date: `2026-05-24T23:21:37Z`
- Entry skill: `skills/omniroute/SKILL.md`
- Checked date: 2026-05-24

## Source Priority

1. A local OmniRoute checkout supplied with `--source-path`, when the operator knows it is the intended source.
2. The upstream Git repository at a pinned commit, tag, or branch supplied with `--ref`.
3. The upstream default branch only for discovery reports, never for final import provenance.

## Refresh Rules

- Refresh this ledger before importing, updating, or removing any converted OmniRoute skill.
- Prefer a pinned commit for conversion metadata.
- Record the commit SHA, commit date, source path, source SHA-256, and access date for every converted skill.
- If upstream disappears or a skill is renamed, classify the local skill as `local-only` until a maintainer confirms removal or migration.

## 2026-05-24 Import Wave

Converted Localsetup skills from the pinned upstream source:

- `omniroute` -> `ls-omniroute`
- `omniroute-a2a` -> `ls-omniroute-a2a`
- `omniroute-chat` -> `ls-omniroute-chat`
- `omniroute-cli` -> `ls-omniroute-cli`
- `omniroute-cli-admin` -> `ls-omniroute-cli-admin`
- `omniroute-cli-cloud` -> `ls-omniroute-cli-cloud`
- `omniroute-cli-eval` -> `ls-omniroute-cli-eval`
- `omniroute-cli-providers` -> `ls-omniroute-cli-providers`
- `omniroute-compression` -> `ls-omniroute-compression`
- `omniroute-embeddings` -> `ls-omniroute-embeddings`
- `omniroute-image` -> `ls-omniroute-image`
- `omniroute-mcp` -> `ls-omniroute-mcp`
- `omniroute-monitoring` -> `ls-omniroute-monitoring`
- `omniroute-routing` -> `ls-omniroute-routing`
- `omniroute-stt` -> `ls-omniroute-stt`
- `omniroute-tts` -> `ls-omniroute-tts`
- `omniroute-web-fetch` -> `ls-omniroute-web-fetch`
- `omniroute-web-search` -> `ls-omniroute-web-search`

Localsetup-native OmniRoute skills retained:

- `ls-omniroute-proxy` with `local_role: proxy-discovery`
- `ls-omniroute-admin-automation` with `local_role: admin-automation`
- `ls-omniroute-update` with `local_role: update-workflow`

## Current Boundary

The bundled updater is report-first. It produces comparison and freshness reports and does not automatically write, remove, or replace converted skill directories.

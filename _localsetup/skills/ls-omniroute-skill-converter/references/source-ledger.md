# OmniRoute Source Ledger

## Upstream

- Repository: `https://github.com/diegosouzapw/OmniRoute`
- Skills root: `skills/`
- Planning-time checked branch head: `89aa761e667b38e25eb044e69b524e90de99cbe9`
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

## Current First-Pass Boundary

The bundled converter is read-only. It produces comparison reports and does not write Localsetup skill directories, metadata, registries, or docs.

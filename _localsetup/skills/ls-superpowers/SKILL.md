---
name: ls-superpowers
description: Wrapper for the Superpowers workflow bundle. Use to map Superpowers workflows
  to Localsetup-native process skills without bulk-importing duplicates.
metadata:
  version: '1.0'
extensions:
  external_skill:
    source_kind: wrapper
    source_url: https://github.com/obra/superpowers
    source_path: <repository inventory>
    source_commit: d884ae04edebef577e82ff7c4e143debd0bbec99
    source_ref: main
    source_sha256: 14160b0f47047b1d8df87e05f166991f1e8a3ecb4a12a45be30ccb133dae9315
    license: MIT
    import_date: '2026-07-03'
    vetting_status: provenance-recorded-no-bundled-tooling-executed
---

# Superpowers Workflow Bundle

Use this skill when working on Superpowers workflow bundle tasks.

## Workflow

- Prefer existing Localsetup-native process skills such as `ls-tdd-guide`, `ls-test-runner`, `ls-debug-pro`, and review workflows.
- Use the upstream bundle as a comparison source for workflow gaps, not as an automatic replacement.
- When importing an individual workflow later, check overlap and preserve stronger Localsetup safety gates.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.


## Upstream Coverage

See [upstream coverage](./references/upstream-coverage.md) for the compact inventory captured during this import wave.

## Provenance

- Source: `https://github.com/obra/superpowers`
- Ref: `main` at `d884ae04edebef577e82ff7c4e143debd0bbec99`
- Source path: `<repository inventory>`
- License classification: `MIT`
- Source SHA-256: `14160b0f47047b1d8df87e05f166991f1e8a3ecb4a12a45be30ccb133dae9315`

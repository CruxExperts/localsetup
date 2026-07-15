---
name: ls-openclaudia-skills
description: Inventory wrapper for OpenClaudia marketing skills. Use when reviewing
  marketing, growth, SEO, ads, analytics, and content-skill coverage.
metadata:
  version: '1.0'
extensions:
  external_skill:
    source_kind: wrapper
    source_url: https://github.com/OpenClaudia/openclaudia-skills
    source_path: <repository inventory>
    source_commit: f97d104d4c2caa7d591d52834d73b0becbf07cd5
    source_ref: main
    source_sha256: 2937fc67e8e540e36445b4fd4caa7e269f89b2f4fe931dcf2394f0a28e4c5507
    license: MIT
    import_date: '2026-07-03'
    vetting_status: provenance-recorded-no-bundled-tooling-executed
---

# Openclaudia Marketing Skills

Use this skill when working on OpenClaudia marketing skills tasks.

## Workflow

- Use this wrapper to triage marketing bundle coverage and avoid duplicate Localsetup skill IDs.
- Do not expose ad-platform, CRM, analytics, or social account credentials during evaluation.
- Prefer native Localsetup skills for repeatable CRO, SEO, content, and email workflows.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.


## Upstream Coverage

See [upstream coverage](./references/upstream-coverage.md) for the compact inventory captured during this import wave.

## Provenance

- Source: `https://github.com/OpenClaudia/openclaudia-skills`
- Ref: `main` at `f97d104d4c2caa7d591d52834d73b0becbf07cd5`
- Source path: `<repository inventory>`
- License classification: `MIT`
- Source SHA-256: `2937fc67e8e540e36445b4fd4caa7e269f89b2f4fe931dcf2394f0a28e4c5507`

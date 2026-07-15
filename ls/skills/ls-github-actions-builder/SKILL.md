---
name: ls-github-actions-builder
description: Guide GitHub Actions workflow authoring. Use for CI, release, scheduled
  jobs, permissions, caching, matrices, artifacts, and secure workflow design.
metadata:
  version: '1.0'
---

# Github Actions

Use this skill when working on GitHub Actions tasks.

## Workflow

- Inspect existing workflow triggers, permissions, concurrency, secrets, environments, and repo rules before editing.
- Use least-privilege `permissions`, pinned action major versions, cache keys with restore strategy, and explicit artifact retention.
- Validate YAML, changed workflow paths, and representative local or CI commands before relying on automation.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.

## Provenance

- Source classification: `official-docs-reference`
- This is a Localsetup-native skill written from project workflow requirements and public/official documentation routing.

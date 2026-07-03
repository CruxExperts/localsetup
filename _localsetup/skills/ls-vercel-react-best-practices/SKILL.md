---
name: ls-vercel-react-best-practices
description: Guide React and Next.js best practices. Use for component boundaries,
  data fetching, rendering performance, server/client split, and Vercel-oriented React
  work.
metadata:
  version: '1.0'
extensions:
  external_skill:
    source_kind: native-reference
    source_url: https://github.com/vercel-labs/agent-skills
    source_path: skills/react-best-practices/SKILL.md
    source_commit: f8a72b9603728bb92a217a879b7e62e43ad76c81
    source_ref: main
    source_sha256: 71ed7794962fa6e803ee83030517b5b93a9f70fbfeb431ec4535c5480a8d8355
    license: NO_REPO_LICENSE_FOUND
    import_date: '2026-07-03'
    vetting_status: provenance-recorded-no-bundled-tooling-executed
---

# React Best Practices

Use this skill when working on React best practices tasks.

## Workflow

- Inspect framework version, router, rendering mode, server/client boundaries, and data-fetching path before refactors.
- Prefer server components and framework-native caching where the project supports them; avoid unnecessary client state.
- Validate with typecheck, lint, tests, and build or route-level smoke checks after behavior changes.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.


## License Boundary

The upstream repository snapshot did not expose a top-level license file during this run. This skill is Localsetup-native guidance and does not copy upstream body text or bundled assets.

## Provenance

- Source: `https://github.com/vercel-labs/agent-skills`
- Ref: `main` at `f8a72b9603728bb92a217a879b7e62e43ad76c81`
- Source path: `skills/react-best-practices/SKILL.md`
- License classification: `NO_REPO_LICENSE_FOUND`
- Source SHA-256: `71ed7794962fa6e803ee83030517b5b93a9f70fbfeb431ec4535c5480a8d8355`

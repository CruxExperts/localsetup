---
name: ls-nodejs-nextjs
description: "Practical Node.js and Next.js project runbook. Use for Node, Next.js, React, package-manager, build, migration, debugging, testing, security, deployment, and version-verification tasks."
metadata:
  version: "1.0"
compatibility:
  notes:
    - "Includes a read-only Node.js verifier because npm registry checks are the domain-specific source of truth for package metadata."
---

# Node.js And Next.js

Use this skill when working on Node.js, Next.js, React, package-manager,
build, migration, debugging, testing, security, deployment, or version
verification tasks.

## Inspect The Project First

Before recommending upgrades or changing code, inspect the project as it is:

- `package.json`: `packageManager`, `engines`, scripts, dependencies,
  devDependencies, `type`, workspaces, lint/test/build commands, and framework
  packages.
- Lockfiles: `package-lock.json`, `npm-shrinkwrap.json`, `pnpm-lock.yaml`,
  `yarn.lock`, `bun.lock`, or `bun.lockb`.
- Runtime pins: `.nvmrc`, `.node-version`, `.tool-versions`, `volta`,
  `.npmrc`, `.yarnrc.yml`, Corepack settings, Dockerfiles, devcontainers, CI,
  and deployment config.
- Next.js config: `next.config.*`, `tsconfig.json`, `jsconfig.json`, `eslint`
  config, `postcss.config.*`, `tailwind.config.*`, middleware/proxy files,
  route handlers, app/pages router usage, and runtime declarations.
- Runtime target: Node server, serverless, Edge Runtime, static export, Docker,
  Vercel, or another host.

Do not apply latest-version guidance blindly to a pinned project. Treat the
lockfile, runtime target, CI, and deploy platform as constraints before changing
Node, Next.js, React, or package-manager versions.

## Decision Tree

- **Setup or install:** identify the package manager from `packageManager` and
  lockfiles; enable Corepack only when the project expects it; run the repo's
  documented install command.
- **Build or runtime failure:** reproduce with the repo script first, identify
  Node/Next/React versions, then isolate whether the failure is dependency,
  config, server/client boundary, environment, or deployment-specific.
- **Migration:** read the project's current major versions and official upgrade
  guides; move one major boundary at a time when risk is high.
- **Dependency change:** confirm peer dependencies and engine ranges; prefer the
  smallest compatible change and record lockfile effects.
- **Tests and quality:** use existing `lint`, `typecheck`, `test`, and `build`
  scripts before adding new tooling.
- **Production deployment:** verify runtime, standalone output, image strategy,
  environment variables, cache behavior, and security headers.
- **Security review:** check user-controlled input, SSR/route handlers, auth,
  secrets, unsafe redirects, middleware, dependency advisories, and deployment
  platform notices.

## Current Stable Snapshot

Volatile facts below were verified on 2026-05-20 UTC from npm registry metadata
and Node release metadata. Re-run
[`scripts/verify-current-versions.mjs`](./scripts/verify-current-versions.mjs)
before relying on them for new work.

- `next` latest is `16.2.6`; `canary` is `16.3.0-canary.24`; `beta` is
  `16.0.0-beta.0`; `rc` is `15.0.0-rc.1`.
- `next@16.2.6` declares Node `>=20.9.0` and React peers
  `^18.2.0 || 19.0.0-rc-de68d2f4-20241204 || ^19.0.0`.
- `react` and `react-dom` latest are `19.2.6`; `react-dom@19.2.6` peers on
  `react ^19.2.6`.
- Node `26.x` is Current; latest dist entry checked was `v26.2.0`.
- Node `24.x` Krypton is Active LTS; latest dist entry checked was `v24.15.0`.
- Node `22.x` Jod is Maintenance LTS; latest dist entry checked was `v22.22.3`.
- Node `20.x` Iron reached end of life on 2026-04-30. It may satisfy some
  framework engine ranges, but it should not be selected for new production
  baselines.

Stable guidance must not treat canary, beta, RC, experimental, or Current Node
releases as production defaults. Use them only when the project explicitly opts
in or the task is research, reproduction, or compatibility testing.

## Reference Map

- [Source ledger](./references/source-ledger.md)
- [Version matrix](./references/version-matrix.md)
- [Next.js latest stable](./references/nextjs-latest-stable.md)
- [Node.js runtime and package management](./references/nodejs-runtime-and-package-management.md)
- [Node.js development best practices](./references/nodejs-development-best-practices.md)
- [Next.js development best practices](./references/nextjs-development-best-practices.md)
- [Debugging runbooks](./references/debugging-runbooks.md)
- [Testing and quality](./references/testing-and-quality.md)
- [Security and deployment](./references/security-and-deployment.md)
- [Update procedure](./references/update-procedure.md)
- [Verified version snapshot](./data/verified-versions.json)
- [Current-version verifier](./scripts/verify-current-versions.mjs)

## Verifier

Use the verifier when current package or runtime facts matter:

```bash
node scripts/verify-current-versions.mjs --help
node scripts/verify-current-versions.mjs
node scripts/verify-current-versions.mjs --json
```

The script is read-only. It performs no installs, makes no dependency changes,
and does not rewrite the snapshot. It fetches npm registry metadata, the Node
release schedule, and the Node dist index, then reports required facts and drift
against `data/verified-versions.json` when that file is present.

## Boundaries

- Respect project-pinned versions before recommending upgrades.
- Do not infer framework support from blog posts or package popularity.
- Do not present beta, canary, RC, experimental, or unreleased behavior as
  stable.
- Do not change package managers or lockfile formats unless the task is
  explicitly about that migration.
- Do not add dependencies when a built-in Node, npm, or framework feature is
  sufficient.

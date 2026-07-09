---
status: ACTIVE
version: 4.2
owner_skill: ls-automatic-versioning
---

# Localsetup Versioning

Localsetup uses the root `VERSION` file as the source of truth for the framework version. README files, generated facts, and release artifacts should display the same normalized semantic version.

## Current Version

- Source of truth: [`../../VERSION`](../../VERSION)
- Current value: `4.2.14`
- Generated facts: [`_generated/facts.json`](_generated/facts.json)

## Policy

- Keep `VERSION`, the root README version line, and generated facts in sync.
- Use Conventional Commits for readable release history. Routine development defaults to one patch bump per release batch, including commits whose subject starts with `feat:`.
- `Release-Type: major|minor|patch|none` is the only way to request a major bump, minor bump, explicit patch bump, or no release bump.
- Breaking markers (`!` or `BREAKING CHANGE:`) are diagnostic only until paired with an explicit `Release-Type:` trailer. `version-plan` fails with an actionable message when a breaking marker appears without that trailer.
- Merge commits, version-sync commits, and fully canceled unreleased reverts do not request a bump.
- Version and documentation sync are automatic. Local hooks plan the bump from outgoing commits, update known version surfaces, regenerate docs artifacts, and create a version-sync commit before push.
- Reverts of unreleased commits cancel the pending bump before push. Reverts of already-published commits are released as a monotonic patch version rather than decreasing `VERSION`.
- Skill versions are separate from the framework version and live in each skill's `SKILL.md` frontmatter under `metadata.version`.
- Workflow package catalog data is regenerated from `_localsetup/workflows/*/workflow.yaml`; version-sync checks include workflow registry, quick reference, and generated workflow catalog surfaces.

## Local workflow

Install hooks once per clone:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . install-hooks
```

For normal release pushes, use:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . release-push
```

Before diagnosing a version or tag mismatch, fetch remote tags so local state
matches GitHub:

```bash
git fetch --tags origin
```

For an unpublished release batch, `version-plan` normally reports `ok: false`
until a version-sync commit exists. Prepare that commit with:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD --fix
```

Raw `git push` is guarded by `.githooks/pre-push`. If a version-sync commit is needed, the hook creates it and stops that push; rerun the push after reviewing the generated commit. This two-step guard is intentional because Git determines the commit being pushed before the `pre-push` hook runs.

Useful read-only checks:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-plan
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"
```

The `version-plan` output includes `policy: "patch-default"`, diagnostic `raw_bump` values from Conventional Commit parsing, and the effective release `bump` after patch-default policy is applied. `version-sync --check --target "$(cat VERSION)"` checks whether the current checked-out version is already synced; it is not the command that chooses the next release version.

## GitHub release workflow

On pushes to `main`, GitHub Actions verifies the computed version plan, confirms all version references and generated docs are committed, runs the framework validation suite, builds the public package artifact, verifies the tarball checksum and embedded artifact metadata, uploads the tarball plus `.sha256` and CycloneDX SBOM sidecars, attests the tarball when GitHub artifact attestation is available, and publishes tag/release `vX.Y.Z`. Existing tags must already point at the current commit or the workflow fails.

## Verification

Before release, run:

```bash
uv lock --check
uv sync --locked --all-groups
git fetch --tags origin
uv run --locked python _localsetup/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD --fix
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-plan
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"
uv run --locked python _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/ls-framework-audit.md
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . scan-migration
uv run --locked python _localsetup/tools/localsetup.py --source-root . audit-global-first
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup.py --source-root . generate-docs
uv run --locked python _localsetup/tools/localsetup.py --source-root . package --out "dist/localsetup-v$(cat VERSION).tar.gz"
uv run --locked python _localsetup/tools/localsetup.py --source-root . verify-release "dist/localsetup-v$(cat VERSION).tar.gz"
git diff --check
```

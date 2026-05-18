---
status: ACTIVE
version: 3.8
owner_skill: ls-automatic-versioning
---

# Localsetup v3 Versioning

Localsetup v3 uses the root `VERSION` file as the source of truth for the framework version. README files, generated facts, and release artifacts should display the same normalized semantic version.

## Current Version

- Source of truth: [`../../VERSION`](../../VERSION)
- Current value: `3.8.7`
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
python3 _localsetup/tools/localsetup_v3.py --source-root . install-hooks
```

For normal release pushes, use:

```bash
python3 _localsetup/tools/localsetup_v3.py --source-root . release-push
```

Raw `git push` is guarded by `.githooks/pre-push`. If a version-sync commit is needed, the hook creates it and stops that push; rerun the push after reviewing the generated commit. This two-step guard is intentional because Git determines the commit being pushed before the `pre-push` hook runs.

Useful read-only checks:

```bash
python3 _localsetup/tools/localsetup_v3.py --source-root . version-plan
python3 _localsetup/tools/localsetup_v3.py --source-root . version-sync --check --target "$(cat VERSION)"
```

The `version-plan` output includes `policy: "patch-default"`, diagnostic `raw_bump` values from Conventional Commit parsing, and the effective release `bump` after patch-default policy is applied.

## GitHub release workflow

On pushes to `main`, GitHub Actions verifies the computed version plan, confirms all version references and generated docs are committed, runs the framework validation suite, builds the public package artifact, verifies the tarball checksum and embedded artifact metadata, uploads the tarball plus `.sha256` and CycloneDX SBOM sidecars, attests the tarball when GitHub artifact attestation is available, and publishes tag/release `vX.Y.Z`. Existing tags must already point at the current commit or the workflow fails.

## Verification

Before release, run:

```bash
python3 _localsetup/tools/localsetup_v3.py --source-root . version-plan
python3 _localsetup/tools/localsetup_v3.py --source-root . version-sync --check --target "$(cat VERSION)"
python3 _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/localsetup-v3-framework-audit.md
python3 _localsetup/tools/localsetup_v3.py --source-root . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --source-root . scan-migration
python3 _localsetup/tools/localsetup_v3.py --source-root . audit-global-first
python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .
python3 _localsetup/tools/localsetup_v3.py --source-root . generate-docs
python3 _localsetup/tools/localsetup_v3.py --source-root . package --out "dist/localsetup-v$(cat VERSION).tar.gz"
python3 _localsetup/tools/localsetup_v3.py --source-root . verify-release "dist/localsetup-v$(cat VERSION).tar.gz"
git diff --check
```

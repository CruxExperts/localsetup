---
status: ACTIVE
version: 3.7
---

# Localsetup v3 Versioning

Localsetup v3 uses the root `VERSION` file as the source of truth for the framework version. README files, generated facts, and release artifacts should display the same normalized semantic version.

## Current Version

- Source of truth: [`../../VERSION`](../../VERSION)
- Current value: `3.7.2`
- Generated facts: [`_generated/facts.json`](_generated/facts.json)

## Policy

- Keep `VERSION`, the root README version line, and generated facts in sync.
- Use Conventional Commits for release history. Breaking commits (`!` or `BREAKING CHANGE:`) bump major. User-facing framework capability changes bump minor. Internal release automation, installer/platform-adapter maintenance, hooks, CI, docs, tests, validation, and packaging changes bump patch even when their commit message uses `feat:`.
- Treat installer, adapter, template, existing skill, config, and framework runtime maintenance as patch by default. Use an explicit `Release-Type: minor` trailer when a change should be marketed as a new public capability.
- Add an explicit `Release-Type: major|minor|patch|none` trailer when the default classification would be too broad or too narrow.
- Version and documentation sync are automatic. Local hooks plan the bump from outgoing commits, update known version surfaces, regenerate docs artifacts, and create a version-sync commit before push.
- Reverts of unreleased commits cancel the pending bump before push. Reverts of already-published commits are released as a monotonic patch version rather than decreasing `VERSION`.
- Skill versions are separate from the framework version and live in each skill's `SKILL.md` frontmatter under `metadata.version`.
- Workflow package catalog data is regenerated from `_localsetup/workflows/*/workflow.yaml`; version-sync checks include workflow registry, quick reference, and generated workflow catalog surfaces.

## Local workflow

Install hooks once per clone:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . install-hooks
```

For normal release pushes, use:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . release-push
```

Raw `git push` is guarded by `.githooks/pre-push`. If a version-sync commit is needed, the hook creates it and stops that push; rerun the push after reviewing the generated commit. This two-step guard is intentional because Git determines the commit being pushed before the `pre-push` hook runs.

Useful read-only checks:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . version-plan
python3 _localsetup/tools/localsetup_v3.py --repo . version-sync --check --target "$(cat VERSION)"
```

The `version-plan` output includes both `raw_bump` from the commit message and final `bump` after path-aware policy is applied.

## GitHub release workflow

On pushes to `main`, GitHub Actions verifies the computed version plan, confirms all version references and generated docs are committed, runs the framework validation suite, builds the public package artifact, verifies the tarball checksum and embedded artifact metadata, uploads the tarball plus `.sha256` and CycloneDX SBOM sidecars, attests the tarball when GitHub artifact attestation is available, and publishes tag/release `vX.Y.Z`. Existing tags must already point at the current commit or the workflow fails.

## Verification

Before release, run:

```bash
python3 _localsetup/tools/localsetup_v3.py --repo . version-plan
python3 _localsetup/tools/localsetup_v3.py --repo . version-sync --check --target "$(cat VERSION)"
python3 _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/localsetup-v3-framework-audit.md
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --repo . scan-migration
python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .
python3 _localsetup/tools/localsetup_v3.py --repo . generate-docs
python3 _localsetup/tools/localsetup_v3.py --repo . package --out "dist/localsetup-v$(cat VERSION).tar.gz"
python3 _localsetup/tools/localsetup_v3.py --repo . verify-release "dist/localsetup-v$(cat VERSION).tar.gz"
git diff --check
```

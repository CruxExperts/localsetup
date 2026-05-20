---
name: ls-automatic-versioning
description: Use and maintain automatic versioning from conventional commits; VERSION as source of truth; sync to READMEs and docs. Use when working on version bumps, release workflow, or when the user asks about versioning or conventional commits.
metadata:
  version: "1.1"
---

# Automatic versioning (framework)

**Purpose:** The framework uses semantic versioning with VERSION as source of truth. Use this skill when implementing, explaining, or changing versioning behavior so it stays consistent and framework-appropriate.

## Source of truth

- **VERSION** (repo root): single line, semantic version `MAJOR.MINOR.PATCH` (e.g. `2.0.0`). This is the only canonical version value.
- **Displayed version** must stay in sync: README and framework README show `**Version:** X.Y.Z`; framework docs use YAML front matter `version: X.Y` (major.minor). The repo tooling keeps these in sync when the release workflow runs.

## Patch-default release policy

- **Default:** normal development batches release as one PATCH increment, including commits that use `feat:` for readability.
- **Explicit release type:** add `Release-Type: major|minor|patch|none` in the commit body to request any non-default release impact or to document an intentional patch/no-bump decision.
- **Breaking markers:** `BREAKING CHANGE:` in the body or type followed by `!` (for example `feat!: new API`) are diagnostics only until paired with `Release-Type:`. `version-plan` fails when a breaking marker is present without the explicit trailer.
- **No bump:** Merge commits, version-sync commits, and fully canceled unreleased reverts.
- **Diagnostics:** `version-plan` keeps `raw_bump` as the Conventional Commit interpretation and `bump` as the effective patch-default release decision.

## In this repo (public framework)

Version bump and doc sync are performed by deterministic repo tooling. Use `uv run --locked python _localsetup/tools/localsetup.py --source-root . release-push` for normal release pushes. Raw `git push` is guarded: if a sync commit is needed, `.githooks/pre-push` creates it and stops the stale push so the next push sends the correct commit.

For read-only release preflight, run `uv run --locked python _localsetup/tools/localsetup.py --source-root . version-plan` and `uv run --locked python _localsetup/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"`.

## Reference

- Versioning doc: [_localsetup/docs/VERSIONING.md](../../docs/VERSIONING.md) is the public reference.

## Rule ownership

This skill owns versioning and release-sync behavior. Keep `VERSION`, generated docs, version-sync path lists, provenance, and release tooling aligned here before updating the public doc.

- `VERSION` is canonical.
- Release impact is controlled by the patch-default policy plus explicit `Release-Type:` trailers.
- Generated docs and generated taxonomy artifacts are part of release sync; do not leave them outside the versioning candidate/staging lists.

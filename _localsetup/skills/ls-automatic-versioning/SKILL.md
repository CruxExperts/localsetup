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

## Conventional Commits -> bump type

- **MAJOR:** `BREAKING CHANGE:` in body, or type followed by `!` (e.g. `feat!: new API`).
- **MINOR:** user-facing framework capability changes. `feat:` is minor unless all changed files are release automation, hooks, CI, docs, tests, validation, or packaging surfaces.
- **PATCH:** `fix:`, `docs:`, `chore:`, `style:`, `refactor:`, `perf:`, `test:`, `ci:`, `build:`, plus internal release automation and maintenance-only changes; any other message defaults to PATCH.
- **Override:** add `Release-Type: major|minor|patch|none` in the commit body when the deterministic default is not the intended release impact.
- **No bump:** Merge commits (message starts with `Merge `).

## In this repo (public framework)

Version bump and doc sync are performed by deterministic repo tooling. Use `python3 _localsetup/tools/localsetup_v3.py --repo . release-push` for normal release pushes. Raw `git push` is guarded: if a sync commit is needed, `.githooks/pre-push` creates it and stops the stale push so the next push sends the correct commit.

## Reference

- Versioning doc: _localsetup/docs/VERSIONING.md in the framework docs.

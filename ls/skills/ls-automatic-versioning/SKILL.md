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

## Explicit sequential logical-slice policy

A repository's explicit release contract can select the canonical planner's
`policy="sequential-logical-slices"` mode. The default remains `patch-default`
for existing converted repositories. Callers must propagate the selected mode
through planning and release consumers; merely documenting a sequential policy
does not activate it. The Python planner exposes this explicit mode; CLI release consumers retain
legacy selection until their repository policy integration selects it.

- Each accepted logical source slice increments once: `feat:` defaults to MINOR and resets PATCH; other source commits default to PATCH. `Release-Type:` declares explicit impact.
- `Release-Slice: lowercase-id` groups unpublished members. Otherwise each source SHA is distinct. The first integrated source member anchors the slice; its highest final member classification determines the single increment. An interleaved later feature member upgrades that original slice without moving it or counting it twice.
- Integration traverses first-parent history, then newly introduced side ancestry in recorded parent order, never author/committer dates.
- Breaking markers require an explicit `Release-Type: major` compatibility decision. Lower/none overrides, duplicate or malformed metadata fail planning.
- Actual merges and generated-only receipts are excluded using changed-path/owned-facts evidence, not subject resemblance. Sync commits must change only canonical version/generated content.
- Each sync's recorded and committed version must match its own ancestry-prefix target; the latest sync and HEAD must match the final target. Incorrect historical syncs require explicit reviewed reconciliation, not automatic exemptions.
- Exact native Git reverts cancel fully reverted unpublished slices only when single-parent raw path/blob/mode changes prove the complete inverse. Mixed changes, conflict-adjusted reverts or later changes to the same affected file require explicit reconciliation; later unrelated files remain untouched. Partial grouped reverts, ambiguous targets and revert-of-revert histories require explicit reconciliation. Reverting published work is a new maintenance outcome.
- Existing plan fields remain. `logical_slices` records anchors, members, classification and before/after versions; `excluded_commits` and `version_sync_checks` explain evidence. Aggregate `bump` is the highest category, not target arithmetic.
- Select and verify the published base explicitly. Comparison/upstream refs are not proof of publication; invalid/nonancestor bases fail. Do not guess historical aliases or use private ledgers as hidden CI configuration.

## In this repo (public framework)

Version bump and doc sync are performed by deterministic repo tooling. Use `uv run --locked python ls/tools/localsetup.py --source-root . release-push` for normal release pushes. Raw `git push` is guarded: if a sync commit is needed, `.githooks/pre-push` creates it and stops the stale push so the next push sends the correct commit.

For read-only release preflight, run `uv run --locked python ls/tools/localsetup.py --source-root . version-plan` and `uv run --locked python ls/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"`.

## Reference

- Versioning doc: [ls/docs/VERSIONING.md](../../docs/VERSIONING.md) is the public reference.

## Rule ownership

This skill owns versioning and release-sync behavior. Keep `VERSION`, generated docs, version-sync path lists, provenance, and release tooling aligned here before updating the public doc.

- `VERSION` is canonical.
- Release impact uses the explicitly selected repository policy; existing callers retain patch-default unless sequential mode is selected.
- Generated docs and generated taxonomy artifacts are part of release sync; do not leave them outside the versioning candidate/staging lists.

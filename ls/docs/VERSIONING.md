---
status: ACTIVE
version: 4.22
owner_skill: ls-automatic-versioning
---

# LocalSetup Versioning

LocalSetup uses the root `VERSION` file as the source of truth for the framework version. README files, generated facts, and release artifacts should display the same normalized semantic version.

## Current Version

- Source of truth: [`../../VERSION`](../../VERSION)
- Current value: `4.22.3`
- Generated facts: [`_generated/facts.json`](_generated/facts.json)

## Policy

- Keep `VERSION`, the root README version line, and generated facts in sync.
- Use Conventional Commits for readable release history. Routine development defaults to one patch bump per release batch, including commits whose subject starts with `feat:`.
- `Release-Type: major|minor|patch|none` is the only way to request a major bump, minor bump, explicit patch bump, or no release bump.
- Breaking markers (`!` or `BREAKING CHANGE:`) are diagnostic only until paired with an explicit `Release-Type:` trailer. `version-plan` fails with an actionable message when a breaking marker appears without that trailer.
- Merge commits, version-sync commits, and fully canceled unreleased reverts do not request a bump.
- `version-plan` derives the target from the base `VERSION` and the net unreleased bump. Every in-range `chore: sync release version X` commit must name that target; when any sync commit is present, the HEAD `VERSION` must also equal it, including no-bump batches.
- Version and documentation sync are automatic. Local hooks plan the bump from outgoing commits, update known version surfaces, regenerate docs artifacts, and create a version-sync commit before push.
- From a clean worktree, `publish-preflight` without `--fix` deliberately prepares direct version surfaces as an unstaged candidate. When it changes files, it returns `prepared_not_ready`; review and commit that candidate, then create and validate the separate generated-document receipt. It never stages or commits the candidate.
- `publish-preflight --fix` is the one-command alternative: it performs the clean preparation plus the version-sync and generated-document commits.
- Reverts of unreleased commits cancel the pending bump before push. Reverts of already-published commits are released as a monotonic patch version rather than decreasing `VERSION`.
- Skill versions are separate from the framework version and live in each skill's `SKILL.md` frontmatter under `metadata.version`.
- Workflow package catalog data is regenerated from `ls/workflows/*/workflow.yaml`; version-sync checks include workflow registry, quick reference, and generated workflow catalog surfaces.

## Explicit sequential policy

The canonical planner selects `sequential-logical-slices` automatically when the
planned HEAD contains a valid, committed `.localsetup-release.json`. This shared
selection applies to `version-plan`, `version-sync`, `publish-preflight`,
`release-push`, the pre-push hook and release CI. Without that file, the existing
`patch-default` policy remains. Python callers can also select sequential mode
explicitly for an unconfigured repository; an explicit argument cannot override
a conflicting committed policy. A loose, deleted or edited worktree policy does
not replace the selected commit's contract. Selection does not authorize publication.

The [release policy schema](../config/release-policy.schema.json) defines the
strict configuration: `schema_version: 1`, `policy: "sequential-logical-slices"`,
an `anchor` with full lowercase commit SHA, canonical `version` and matching
`vMAJOR.MINOR.PATCH` tag, and an `overrides` array. The file must be a regular Git
blob of at most 64 KiB. Duplicate keys, unknown fields, invalid types and duplicate
override SHAs fail planning. The planner verifies the anchor's committed VERSION
and ancestry locally; maintainers must independently verify that the named tag
and commit were actually published. Planning never fetches release information.

Each optional override has exactly `commit`, `slice` and `classification` fields.
It names one full unpublished source SHA, a lowercase slice ID of at most 128
characters, and `none|patch|minor|major`. Overrides can reconcile reviewed legacy
classification and grouping without changing commit messages or `raw_bump`.
They cannot name merges, generated receipts, reverts or already-published work,
or downgrade breaking changes. They apply consistently to the final fold and
historical sync prefixes; no subject similarity or global name deduplication is
used. Preserve source ancestry when integrating exact-SHA mappings.

The repository-only policy is excluded from release archives and must not be
copied into converted projects. After verifying a newly published tag, advance
the anchor to that exact published commit/version and remove overrides already
covered by it. Review and commit that policy change as ordinary source work;
never rewrite existing history or hand-edit generated versions to force a match.

A `feat:` source slice defaults to MINOR and resets PATCH; other source changes
default to PATCH, with `Release-Type: major|minor|patch|none` for explicit impact.
`Release-Slice: lowercase-id` groups unpublished members; an unlabelled source
uses its unique SHA. The first integrated member anchors the slice, and the
highest classification among its final members determines its one increment.
For example, patch foundation A, independent patch B and a later minor member
of A yield one minor increment for A followed by one patch for B.

Integration order follows first-parent history before newly introduced side
ancestry in Git parent order; timestamps do not order releases. Actual merge
commits and generated-only receipts do not increment the version. Receipt
exclusion validates changed paths and restricts mixed authored files to generated
facts blocks. A receipt-like subject alone grants no exclusion. Sync exclusions
compare canonical version/generated content rather than exempting arbitrary docs.

Breaking markers require an explicit `Release-Type: major` compatibility decision.
Minor, patch and none cannot conceal them. Duplicate/invalid metadata, ambiguous
reverts and partial logical-slice reverts fail for reviewed reconciliation. Exact
native Git revert SHAs cancel fully reverted unpublished slices only after a
single-parent raw path/blob/mode comparison proves the complete inverse. Mixed
changes, conflict-adjusted reverts and later changes to affected files require
explicit reconciliation; later unrelated files remain untouched. Published work
is reverted as a new maintenance outcome.

Each historical sync is checked against its own ancestor-prefix target, including
its committed VERSION. The latest sync and HEAD must match the final target.
Incorrect historical syncs make the plan nonrepairable and stop mutation before
version files change. Ordinary target drift remains repairable through canonical
sync tooling. With committed policy, `--base` is comparison metadata and arithmetic
always starts at the verified anchor. In explicit unconfigured sequential mode,
the selected base must be an ancestor. Upstream refs alone do not prove publication.

Sequential output retains the existing fields and adds `logical_slices` (slice,
anchor, source_shas, classification, before_version, after_version),
`excluded_commits`, `version_sync_checks`, `latest_sync_matches_target`,
`repairable`, `anchor`, `release_overrides`, `comparison_base` and
`comparison_base_resolution`. `base` and `base_resolution` identify the arithmetic
anchor; comparison metadata records the caller's independently selected ref.
`bump` is the highest applied category for compatibility; target_version is the
ordered fold, not one application of that aggregate category.

## Local workflow

Install hooks once per clone:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . install-hooks
```

For normal release pushes, use:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . release-push
```

Before diagnosing a version or tag mismatch, fetch remote tags so local state
matches GitHub:

```bash
git fetch --tags origin
```

For an unpublished release batch, `version-plan` normally reports `ok: false`
until a version-sync commit exists. First prepare the direct, unstaged candidate
from a clean worktree:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD
```

If the result is `prepared_not_ready`, inspect and commit the direct
version-sync candidate, then generate and validate its post-version
generated-document receipt. Use `--fix` only when the tool should prepare and
commit both slices:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD --fix
```

Raw `git push` is guarded by `.githooks/pre-push`. If a version-sync commit is needed, the hook creates it and stops that push; rerun the push after reviewing the generated commit. This two-step guard is intentional because Git determines the commit being pushed before the `pre-push` hook runs.

Useful planning check:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . version-plan
```

The `version-plan` output includes the selected `policy`, diagnostic `raw_bump` values from Conventional Commit parsing, the effective release `bump`, and `version_sync_matches_target` for validating in-range version-sync commits.

## GitHub release workflow

On pushes to `main`, GitHub Actions verifies the computed version plan, confirms all version references and generated docs are committed, runs the framework validation suite, builds the public package artifact, verifies the tarball checksum and embedded artifact metadata, uploads the tarball plus `.sha256` and CycloneDX SBOM sidecars, attests the tarball when GitHub artifact attestation is available, and publishes tag/release `vX.Y.Z`. Existing tags must already point at the current commit or the workflow fails.

## Verification

Before release, run:

```bash
uv lock --check
uv sync --locked --all-groups
git fetch --tags origin
uv run --locked python ls/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD
# Review and commit a prepared_not_ready direct version-sync candidate, then create and validate its generated-doc receipt.
uv run --locked python ls/tools/localsetup.py --source-root . version-plan
uv run --locked python ls/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/ls-framework-audit.md
uv run --locked python ls/tools/localsetup.py --source-root . validate-catalog
uv run --locked python ls/tools/localsetup.py --source-root . scan-migration
uv run --locked python ls/tools/localsetup.py --source-root . audit-global-first
uv run --locked python ls/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python ls/tools/localsetup.py --source-root . generate-docs
uv run --locked python ls/tools/localsetup.py --source-root . package --out "dist/localsetup-v$(cat VERSION).tar.gz"
uv run --locked python ls/tools/localsetup.py --source-root . verify-release "dist/localsetup-v$(cat VERSION).tar.gz"
git diff --check
```

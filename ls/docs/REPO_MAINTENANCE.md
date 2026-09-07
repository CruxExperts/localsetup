---
status: ACTIVE
version: 4.22
owner_skill: ls-framework-compliance
---

# Repository Maintenance

This checklist records the GitHub settings and repo-maintenance conventions that are not fully represented by tracked files. Keep tracked automation in `.github/`; apply remote settings in GitHub after validating the workflow names emitted by Actions.

## Required Local Gates

Run these before a maintainer release or broad automation change:

```bash
git status --short --branch
uv lock --check
uv sync --locked --all-groups
git fetch --tags origin
uv run --locked python ls/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD
# Review and commit a prepared_not_ready direct version-sync candidate, then create and validate its generated-doc receipt.
uv run --locked python ls/tools/localsetup.py --source-root . version-plan
./ls/tools/verify_context
./ls/tools/verify_rules
uv run --locked python ls/tools/localsetup.py --source-root . validate-catalog
uv run --locked python ls/tools/localsetup.py --source-root . validate-package-surface
uv run --locked python ls/tools/localsetup.py --source-root . scan-migration
uv run --locked python ls/tools/localsetup.py --source-root . audit-global-first
uv run --locked python ls/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python ls/tools/localsetup.py --source-root . generate-docs
uv run --locked python ls/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/ls-framework-audit.md
workers="$(uv run --locked python ls/tools/localsetup.py --source-root . test-workers)"
uv run --locked pytest -n "$workers" ls/tests -q
uv run --locked ./ls/tests/automated_test.sh
git diff --check
```

For daily maintenance and ordinary framework edits, run focused tests and matching LocalSetup validators first. Use the full Python suite above as final consolidation for broad automation changes, release or publish readiness, dependency changes, or explicit maintainer requests. Resolve the permitted worker count with `localsetup test-workers`; [COMMAND_REFERENCE.md](COMMAND_REFERENCE.md) owns its formula and aggregate-budget rule.

## Unit-Test Concurrency Policy

Unless a repository explicitly defines a stricter policy, every unit-test runner—regardless of language or framework—uses one aggregate budget: `max(1, floor(available CPU cores / 3))`. Round down before applying the minimum of one worker. Concurrent test processes share that budget rather than each claiming the full allowance.

## Managed Adapter Refresh

Run this after changing shipped skills, workflow packages, platform adapters, or repo agent context when this machine should immediately use the current checkout:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . self-refresh --dependency-mode prompt-only
```

The command installs every configured pack from this checkout into the managed LocalSetup library. Adapter refresh uses validated recorded clients, paths, scopes, modes, and package exposure; new catalog clients sharing a directory do not become owners. A legacy shared path without recorded ownership requires explicit `--platforms` or ownership reconciliation before refresh. Explicit legacy selection uses the normal preservation and native prerequisite checks.

For validated modern receipts, pack and global package overrides change the shared library selection while target exposure remains recorded. Changing recorded clients, target package selectors, scope, or adapter mode requires an explicit install or the owning migration command; self-refresh refuses these combinations before dependency work. It is maintenance tooling for local machine state, not a release or publish step.

Without an explicit platform override, a fresh target with no recorded installation or adapter surface receives a library-only refresh; self-refresh does not select clients for it.

## Maintainer Codex Adapter Reconciliation

This source checkout may expose every public LocalSetup skill and workflow package through its repo-local `.agents/skills` adapter while keeping the global/default skill stance curated. Use this only for the LocalSetup maintainer repo, not as a normal consumer-repo default.

Dry-run first:

```bash
UV_CACHE_DIR=/tmp/localsetup-uv-cache uv run --locked python ls/tools/localsetup.py --source-root . install --target-directory . --platforms codex --global-packs bootstrap core dev frontend architecture ops publishing omniroute --global-skills ls-firecrawl ls-cloudflare-dns --global-exclude-skills ls-superpowers --repo-preset all --mode symlink --json
```

Apply the same plan only after the dry-run has no warnings; the apply-time preflight remains authoritative and will still stop before mutation on same-name adapter collisions:

```bash
UV_CACHE_DIR=/tmp/localsetup-uv-cache uv run --locked python ls/tools/localsetup.py --source-root . install --target-directory . --platforms codex --global-packs bootstrap core dev frontend architecture ops publishing omniroute --global-skills ls-firecrawl ls-cloudflare-dns --global-exclude-skills ls-superpowers --repo-preset all --mode symlink --apply --json
```

Same-name selected package collisions still block before mutation. If a repo-local adapter entry intentionally shadows a selected LocalSetup package, resolve that one entry deliberately before rerunning the native installer; do not clear the adapter directory or broaden the global Codex adapter to make the apply pass.

Verify the reconciled shape:

```bash
UV_CACHE_DIR=/tmp/localsetup-uv-cache uv run --locked python ls/tools/localsetup.py --source-root . verify --target-directory . --platforms codex --level filesystem --json
UV_CACHE_DIR=/tmp/localsetup-uv-cache uv run --locked python ls/tools/localsetup.py --source-root . validate-catalog
```

## GitHub Actions

- `pr-validation` is the required PR and merge-queue validation workflow.
- `generated docs and version sync` catches missing version-sync commits and generated-doc drift before merge.
- `framework validation py3.10` and `framework validation py3.12` cover the supported Python floor and current runtime.
- `shell smoke and framework audit` runs the shell wrapper, framework audit, and whitespace diff check.
- `publish` remains main-only and release-focused. It should not be a maintainer's first signal that version sync is missing.
- `triage` labels issues and PRs from metadata only. It must not check out or run untrusted pull request code.
- `triage` also bootstraps the maintainer label set used by issue forms and Dependabot. Run it manually once with `workflow_dispatch` before enabling Dependabot on a fresh repository.

## Recommended Branch Ruleset For `main`

Configure the active `main` ruleset to:

- Require pull requests before merge.
- Require at least one approving review.
- Require resolved conversations.
- Require status checks to pass before merge.
- Require the `pr-validation` jobs listed above.
- Block deletions and non-fast-forward updates.
- Keep force pushes disabled.
- Enable merge queue only after `merge_group` checks are green on this repository.

## Merge Policy

Prefer squash merges for ordinary PRs so each merged change has one Conventional Commit subject that the release tooling can classify. Use a merge commit for release PRs that contain a version-sync/generated-doc commit; provenance regeneration follows the merged PR's second parent to preserve the source commit recorded in generated artifacts. Never squash or rebase those release PRs. Delete branches on merge when safe.

## Security Settings

Enable these in GitHub security settings where available:

- Dependabot security updates.
- Secret scanning.
- Push protection.
- CodeQL default setup for code scanning.
- Private vulnerability reporting.

Security-sensitive reports should follow [`../../SECURITY.md`](../../SECURITY.md).

## Dependabot

Tracked configuration lives at [`../../.github/dependabot.yml`](../../.github/dependabot.yml). It covers:

- GitHub Actions updates.
- Python dependency updates for the root uv project (`pyproject.toml` and `uv.lock`).

Keep Dependabot PRs small, grouped, and scheduled. Treat dependency updates that affect install, transport, security, or packaging as release-relevant. Pull requests from Dependabot run an extra uv lock/sync validation job, while the standard validation jobs continue to use frozen uv sync/run commands.

## Labels

Keep labels aligned with the triage workflow and issue forms:

- `status/needs-triage`, `status/blocked`, `status/accepted`, `status/ready`
- `type/bug`, `type/feature`, `type/maintenance`, `type/pr`, `type/support`
- `area/docs`, `area/installer`, `area/skills`, `area/release`, `area/automation`, `area/python`
- `priority/high`, `priority/normal`, `priority/low`
- `good first issue`, `help wanted`, `security`, `release`, `docs`, `needs-repro`, `dependencies`

The triage workflow bootstraps these labels. Run the workflow manually once before enabling Dependabot on a fresh repository, then review colors, descriptions, and taxonomy periodically.

## Issues, Discussions, And Projects

- Keep Issues enabled for actionable bugs, features, and maintenance reports.
- Keep Discussions enabled for usage questions and design conversation.
- Use Projects automation to move new issues and PRs into triage and closed or merged items to done.
- Keep blank issues disabled so reports use structured fields.

## Release Policy

`VERSION` is the source of truth. Use [`VERSIONING.md`](VERSIONING.md) for the policy and command flow. Fetch tags before diagnosing a version or release mismatch, because stale local tags can make an already-published GitHub release look missing. For a pending release batch, `version-plan` is expected to report `ok: false` until the version-sync commit exists.

From a clean worktree, prepare the local direct version-sync candidate with:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . publish-preflight --base origin/main --head HEAD
```

When it returns `prepared_not_ready`, inspect and commit that unstaged direct
candidate, then create and validate the post-version generated-document receipt.
Use `--fix` only when the tool should prepare and commit both release slices.

Then push through:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . release-push
```

Do not publish a release from a dirty worktree. If a tag already exists at a different commit, stop and resolve the remote release state before retrying.

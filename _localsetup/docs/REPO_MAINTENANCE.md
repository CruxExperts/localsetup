---
status: ACTIVE
version: 4.1
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
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-plan
uv run --locked python _localsetup/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
uv run --locked python _localsetup/tools/localsetup.py --source-root . validate-catalog
uv run --locked python _localsetup/tools/localsetup.py --source-root . scan-migration
uv run --locked python _localsetup/tools/localsetup.py --source-root . audit-global-first
uv run --locked python _localsetup/tools/generate_docs_artifacts.py --repo-root .
uv run --locked python _localsetup/tools/localsetup.py --source-root . generate-docs
uv run --locked python _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/localsetup-framework-audit.md
uv run --locked pytest -n auto _localsetup/tests -q
uv run --locked ./_localsetup/tests/automated_test.sh
git diff --check
```

## Managed Adapter Refresh

Run this after changing shipped skills, workflow packages, platform adapters, or repo agent context when this machine should immediately use the current checkout:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . self-refresh --dependency-mode prompt-only
```

The command installs every configured pack from this checkout into the managed Localsetup library and refreshes only adapter paths that are already attached in the target repo. It is maintenance tooling for local machine state, not a release or publish step.

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

Prefer squash merges so each merged PR has one Conventional Commit subject that the release tooling can classify. Keep merge commits disabled unless maintainers explicitly need branch history preserved for a specific change. Delete branches on merge when safe.

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

`VERSION` is the source of truth. Use [`VERSIONING.md`](VERSIONING.md) for the policy and command flow. Version sync should be produced locally before push through the hook or:

```bash
uv run --locked python _localsetup/tools/localsetup.py --source-root . release-push
```

Do not publish a release from a dirty worktree. If a tag already exists at a different commit, stop and resolve the remote release state before retrying.

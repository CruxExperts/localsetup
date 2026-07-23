# Contributing to Localsetup

Thanks for helping improve Localsetup. This project is built for people who want agent workflows to be portable, reviewable, and safe enough to use on real repositories.

## Best ways to contribute

- **Report bugs:** Open a GitHub Issue with the Localsetup version, install command, platform ID, OS/WSL2 context, expected behavior, actual behavior, validation output, and relevant short logs.
- **Suggest features:** Open a feature request with the workflow you are trying to improve, the affected skill/workflow/platform/docs area, and why it belongs in the framework.
- **Report maintenance problems:** Use the maintenance issue form for version-sync failures, generated-doc drift, publish workflow failures, or package-artifact issues.
- **Improve docs:** Keep changes focused, practical, and linked to the source docs they clarify.
- **Add or improve skills:** Follow the Agent Skills spec and the framework normalization rules before proposing a new skill.

## Pull request expectations

- Target `main`.
- Keep the PR focused on one problem or one closely related set of docs.
- Use Conventional Commit style for commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`, or `type!:`.
- Explain what changed, why it changed, and any compatibility impact across supported agent platforms.
- Include verification results when touching install behavior, path resolution, generated docs, skills, release tooling, or platform templates.
- Fill out the pull request template. If the change needs a version-sync commit, include it before asking for review.

## Release and maintenance checks

Use the versioning policy in [ls/docs/VERSIONING.md](ls/docs/VERSIONING.md). For automation, branch rules, required checks, labels, and triage behavior, use [ls/docs/REPO_MAINTENANCE.md](ls/docs/REPO_MAINTENANCE.md).

Before opening a release-impacting PR, run the relevant subset of:

```bash
uv run --locked python ls/tools/localsetup.py --source-root . version-plan
uv run --locked python ls/tools/localsetup.py --source-root . version-sync --check --target "$(cat VERSION)"
uv run --locked python ls/tools/localsetup.py --source-root . validate-catalog
uv run --locked python ls/tools/localsetup.py --source-root . validate-package-surface
uv run --locked python ls/tools/localsetup.py --source-root . docs-align check --ci
workers="$(uv run --locked python ls/tools/localsetup.py --source-root . test-workers)"
uv run --locked pytest -n "$workers" ls/tests -q
git diff --check
```

Run focused tests and Localsetup validators for the code you changed before the full Python suite. Treat the full Python suite as final consolidation for broad framework changes, release/publish work, dependency changes, or explicit maintainer review requests. Resolve the permitted worker count with `localsetup test-workers`; the [command reference](ls/docs/COMMAND_REFERENCE.md) owns its formula and aggregate-budget rule.

## Repository layout

- Root files contain the public README, install entrypoints, license, contribution guide, and security policy.
- `ls/` contains the framework engine: tools, configuration, templates, docs, tests, and shipped skills.
- `ls/skills/ls-*` is the source of truth for shipped skills.
- `ls/docs/` is the public framework documentation set.
- `assets/` contains public README and docs visuals.

## Standards

- Keep public docs ASCII-first and GitHub-friendly.
- Do not add machine-specific paths, private hostnames, personal contact details, secrets, or generated private state.
- Do not edit generated docs by hand when a generator owns the content. Update the generator or source data instead.
- Treat imported third-party skills as untrusted until vetted, normalized, and tested.
- Preserve platform-specific differences when they are real. Do not flatten Cursor, Claude Code, Codex, OpenClaw, Kilo, and OpenCode into one imaginary host.

## Attribution

Only humans are listed as contributors. Do not add AI assistants, IDEs, or tools as co-authors in commits or contributor lists.

## Useful references

- [Root README](README.md)
- [Framework README](ls/README.md)
- [Quickstart](ls/docs/QUICKSTART.md)
- [Command reference](ls/docs/COMMAND_REFERENCE.md)
- [Skill importing](ls/docs/SKILL_IMPORTING.md)
- [Versioning](ls/docs/VERSIONING.md)
- [Repository maintenance](ls/docs/REPO_MAINTENANCE.md)
- [Support](SUPPORT.md)
- [Security](SECURITY.md)

# Contributing to Localsetup v3

Thanks for helping improve Localsetup v3. This project is built for people who want agent workflows to be portable, reviewable, and safe enough to use on real repositories.

## Best ways to contribute

- **Report bugs:** Open a GitHub Issue with the Localsetup version, install command, platform ID, OS/WSL2 context, expected behavior, actual behavior, validation output, and relevant short logs.
- **Suggest features:** Open a feature request with the workflow you are trying to improve, the affected skill/workflow/platform/docs area, and why it belongs in the framework.
- **Improve docs:** Keep changes focused, practical, and linked to the source docs they clarify.
- **Add or improve skills:** Follow the Agent Skills spec and the framework normalization rules before proposing a new skill.

## Pull request expectations

- Target `main`.
- Keep the PR focused on one problem or one closely related set of docs.
- Use Conventional Commit style for commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `ci:`, or `type!:`.
- Explain what changed, why it changed, and any compatibility impact across supported agent platforms.
- Include verification results when touching install behavior, path resolution, generated docs, skills, release tooling, or platform templates.

## Repository layout

- Root files contain the public README, install entrypoints, license, contribution guide, and security policy.
- `_localsetup/` contains the framework engine: tools, configuration, templates, docs, tests, and shipped skills.
- `_localsetup/skills/ls-*` is the source of truth for shipped skills.
- `_localsetup/docs/` is the public framework documentation set.
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
- [Framework README](_localsetup/README.md)
- [Quickstart](_localsetup/docs/QUICKSTART.md)
- [Skill importing](_localsetup/docs/SKILL_IMPORTING.md)
- [Versioning](_localsetup/docs/VERSIONING.md)
- [Security](SECURITY.md)

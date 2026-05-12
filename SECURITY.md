# Security

Localsetup v3 manages agent context, skills, install paths, and automation helpers. Please report security-sensitive issues privately so they can be fixed before public disclosure.

## Reporting a vulnerability

1. Do not open a public Issue with exploit details, secrets, hostnames, logs, or private paths.
2. Use GitHub private vulnerability reporting for this repository if it is enabled.
3. If private reporting is not available, use the security contact request issue form, but do not include vulnerability details, exploit steps, secrets, hostnames, private paths, or sensitive logs.

Include the affected file or command, Localsetup version, platform ID if relevant, reproduction steps, expected impact, and whether the issue affects install behavior, skill import, agent permissions, generated docs, package boundaries, or release artifacts.

## Scope

This policy covers:

- Root install scripts and v3 install tooling
- `_localsetup/tools/`, `_localsetup/lib/`, and `_localsetup/config/`
- Shipped skills under `_localsetup/skills/`
- Public templates, docs, package metadata, and generated release artifacts

Out of scope:

- Vulnerabilities in third-party agent hosts, shells, editors, Git, Python, operating systems, or user-provided projects
- Unsafe behavior introduced by locally modified or third-party skills after import
- Secrets or private data that users add to their own repositories

## Security model

- Framework source is repo-local and reviewable.
- Managed skill installs are recreated from `_localsetup/skills/`.
- Generated adapter paths are install output, not source of truth.
- Third-party skills must be treated as untrusted until vetted and normalized.
- Privileged server workflows should use the human-in-the-loop tmux flow and explicit sudo readiness checks.
- Secrets, credentials, private state, and machine-specific files must not be committed.

## Public disclosure

Please allow reasonable time for triage and a fix before publishing technical details. Security fixes should include verification steps and, when relevant, docs updates that explain the safer workflow.

## Repository security settings

Maintainers should keep Dependabot security updates, secret scanning, push protection, CodeQL default setup, and private vulnerability reporting enabled when GitHub makes those settings available for this repository. The maintainer checklist lives in [_localsetup/docs/REPO_MAINTENANCE.md](_localsetup/docs/REPO_MAINTENANCE.md).

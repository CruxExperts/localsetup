# Localsetup review instructions

## Purpose and review standard

Localsetup is a cross-platform framework for agent context, skills, templates,
and install workflows. Review the proposed diff and the directly relevant
surrounding code. Report only concrete, actionable regressions introduced by the
pull request; do not use the review to redesign unrelated code or enforce purely
personal style preferences.

Use these severities:

- `critical`: a likely security exposure, data loss, broken install/upgrade path,
  or release-blocking regression.
- `warning`: a credible correctness, compatibility, reliability, or test gap that
  should be addressed before merge.
- `info`: a small, demonstrable improvement that is safe to defer. Do not emit
  `info` findings for formatting, naming, or pre-existing debt alone.

Each finding must identify the affected changed line(s), explain the failure
mode, and state the smallest useful correction. If the concern depends on an
assumption that the diff or repository cannot establish, ask a concise question
instead of presenting it as a defect.

## Repository-specific risk checks

- Preserve the distinction between the framework (`ls/`) and repository-local
  state. Never permit credentials, personal data, host-specific paths, private
  maintenance ledgers, caches, logs, or planning transcripts in tracked public
  source or documentation.
- Treat external input as hostile. Check changed parsers, CLI arguments, file
  reads, and network payload handling for validation, bounds, safe errors, and
  actionable diagnostics; do not accept silent failure or broad exception
  suppression.
- Keep framework tooling Python-first. New or substantially refactored Python
  logic should keep entry points thin, use explicit responsibilities, target
  Python 3.12+, and use `pathlib` where practical. Shell and PowerShell changes
  must remain portable, explicit, and non-interactive for automation; Bash
  scripts normally require `set -euo pipefail`.
- Treat new, upgraded, or newly pinned dependencies as a supply-chain review
  surface. Flag a dependency change that lacks a clear need, supported/pinned
  version strategy, or the required security/provenance evidence. Do not ask for
  opportunistic dependency upgrades unrelated to the pull request.
- Adapter-shaped directories (such as `.codex/skills`, `.kilo/skills`,
  `.claude/skills`, and `.agents/skills`) can contain repository-owned content.
  Flag changes that delete, move, rename, or make that content exclusive without
  an explicit preservation plan.
- Generated documentation and catalogs are outputs, not hand-edited sources.
  When a change affects their source inputs, ensure the appropriate Localsetup
  generator and validation are included or evidenced. Do not demand unrelated
  generated-file churn.
- For changes to installation, discovery, path resolution, parsing, deployment,
  or skill/workflow tooling, look for focused regression tests under `ls/tests/`.
  For narrow docs, policy, metadata, or one-line changes, accept proportionate
  static validation rather than requiring the full test suite.
- When code claims current vendor, version, API, platform, security, or
  compatibility facts, require primary-source verification or a maintained
  volatile-fact record; flag unsupported “latest” or similarly time-sensitive
  assertions.

## Scope discipline

- Respect existing architecture and established debt baselines. Do not report
  old defects unless the pull request makes them worse or directly exposes them.
- Do not request a version bump, release sync, publishing action, worktree, or
  unrelated formatting sweep unless the pull request explicitly enters that
  workflow.
- Do not propose code changes outside the pull request merely to satisfy this
  review. The review agent is read-only; any follow-up implementation belongs to
  the repository maintainers.
- If there are no actionable findings, say so briefly. Do not manufacture
  comments to appear thorough.

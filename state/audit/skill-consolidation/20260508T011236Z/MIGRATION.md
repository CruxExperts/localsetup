# Skill Consolidation Migration

Timestamp: `20260508T011236Z`

## Checkpoint

- Branch: `skill-consolidation-agents-20260508T011236Z`
- Pre-change checkpoint commit: `977cc58`
- Post-change consolidation commit: `pending`
- Excluded rollback archive: `/tmp/localsetup-skill-consolidation-excluded-20260508T011236Z.tar.gz`

## Archived Variants

- `localsetup-source`: 50 skills from `_localsetup/skills`

Variant hashes are recorded in `variant-file-hashes.sha256`.

## Consolidated Winners

Canonical runtime path: `.agents/skills/<skill>/SKILL.md`

Winner source is `state/audit/skill-consolidation/20260508T011236Z/winners/skills`.

Decision notes:

- All 50 skills: chosen from `_localsetup/skills` because no active platform runtime copies existed under `.kilo`, `.codex`, `.cursor`, `.opencode`, or `.claude`, and `_localsetup/skills` is the complete framework source.

Winner hashes are recorded in `winner-file-hashes.sha256`.

## Validation

- `.agents/skills` count: 50 skills.
- Winner archive count: 50 skills.
- Registry/frontmatter/SHA validation: passed for 50 skills.
- Archive comparison: `diff -qr .agents/skills state/audit/skill-consolidation/20260508T011236Z/winners/skills` passed.
- Compatibility links: `.kilo/skills`, `.codex/skills`, `.cursor/skills`, `.opencode/skills`, and `.claude/skills` point to `../.agents/skills`.
- Deploy dry run: `python3 _localsetup/tools/deploy.py --root <tmp> --tools cursor,claude-code,codex,opencode,kilo --scope local` passed.
- Smoke tests: `./_localsetup/tests/automated_test.sh` passed, 8 passed and 0 failed.
- Python syntax: `python3 -m py_compile _localsetup/tools/deploy.py` passed.
- Whitespace: `git diff --check -- ':!state/audit/skill-consolidation/20260508T011236Z/**'` passed.
- Pytest: not run because `pytest` is not installed and the repo does not declare it in requirements/config.

## Rollback

1. Save or commit post-migration work that should survive rollback.
2. Reset to `977cc58`.
3. Restore excluded runtime/cache material from `/tmp/localsetup-skill-consolidation-excluded-20260508T011236Z.tar.gz` if needed.

# Localsetup v3 Versioning

Localsetup v3 uses the root `VERSION` file as the source of truth for the framework version. README files, generated facts, and release artifacts should display the same normalized semantic version.

## Current Version

- Source of truth: [`../../VERSION`](../../VERSION)
- Current value: `3.0.0`
- Generated facts: [`_generated/facts.json`](_generated/facts.json)

## Policy

- Keep `VERSION`, the root README version line, and generated facts in sync.
- Use conventional commit prefixes such as `feat:`, `fix:`, `chore:`, and `revert:` for release history.
- Repository owners handle official version bumps and generated documentation refreshes.
- Skill versions are separate from the framework version and live in each skill's `SKILL.md` frontmatter under `metadata.version`.

## Verification

Before release, run:

```bash
python3 _localsetup/skills/ls-framework-audit/scripts/run_framework_audit.py --output /tmp/localsetup-v3-framework-audit.md
python3 _localsetup/tools/localsetup_v3.py --repo . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --repo . scan-migration
git diff --check
```

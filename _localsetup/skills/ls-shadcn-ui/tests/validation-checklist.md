# Validation Checklist

- `python3 scripts/verify_shadcn_sources.py --help`
- `python3 scripts/verify_shadcn_sources.py`
- `python3 scripts/verify_shadcn_sources.py --json`
- `python3 scripts/verify_shadcn_sources.py --refresh --json` when current
  upstream source facts matter.
- `python3 _localsetup/tools/localsetup_v3.py --source-root . validate-catalog`
- `python3 _localsetup/tools/skill_validation_scan.py _localsetup/skills --scan-root . --no-fetch`
- `agentskills validate _localsetup/skills/ls-shadcn-ui` when available.
- `python3 _localsetup/tools/generate_docs_artifacts.py --repo-root .`
- `python3 _localsetup/tools/localsetup_v3.py --source-root . generate-docs`
- `git diff --check`

For project-specific shadcn/ui work, also run the target project's typecheck,
lint, tests, and build scripts when available.

# Update Procedure

Use this when refreshing the skill's volatile version facts.

## Steps

1. From the repo root, run the verifier:

   ```bash
   node _localsetup/skills/ls-nodejs-nextjs/scripts/verify-current-versions.mjs --json
   ```

2. Compare the output with `data/verified-versions.json`.
3. If facts changed, update:
   - `data/verified-versions.json`
   - `SKILL.md` current stable snapshot
   - `references/version-matrix.md`
   - `references/nextjs-latest-stable.md`
   - any reference that names the changed release line or date
4. Keep source URLs and verification timestamps next to the changed facts.
5. Run:

   ```bash
   node _localsetup/skills/ls-nodejs-nextjs/scripts/verify-current-versions.mjs --json
   uv run --locked python _localsetup/tools/skill_validation_scan.py _localsetup/skills/ls-nodejs-nextjs --scan-root . --no-fetch
   uv run --locked python _localsetup/tools/localsetup_v3.py --source-root . validate-catalog
   git diff --check
   ```

## Rules

- Do not rewrite stable guidance from non-stable channels.
- Keep canary, beta, RC, experimental, Current, Active LTS, Maintenance LTS, and
  EOL labels distinct.
- If a project is pinned to older versions, use that project's versions for
  implementation decisions and use this skill only as context.

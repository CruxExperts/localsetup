---
name: ls-omniroute-update
description: Coordinate OmniRoute update workflows, including upstream skill discovery, consolidated Localsetup coverage comparison, freshness validation, and report-first import, update, modification, or removal planning. Use when listing, checking, updating, modifying, importing, or removing OmniRoute-derived Localsetup skills.
metadata:
  version: "1.1"
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: update-workflow
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_ref: v3.8.48
    source_commit: 7ee5bbc64dbb03e967521227f2afffeb7c9dad1e
    package_version: 3.8.48
    release_package_commit: 7ee5bbc64dbb03e967521227f2afffeb7c9dad1e
---

# Omni Route Update

Purpose: provide the repeatable, report-first workflow for OmniRoute updates, including tracking skills from `diegosouzapw/OmniRoute` and deciding what Localsetup should cover with native skills, import, refresh, keep, or remove.

## When to use

Use this skill when a task involves any of these phrases or intents:

- Discover upstream OmniRoute skills.
- Compare Localsetup OmniRoute coverage with upstream OmniRoute skills.
- Plan an OmniRoute skill import, update, modification, or removal.
- Check whether a converted OmniRoute skill is current or stale.
- Produce a report before changing the consolidated native pack or handing work to `ls-skill-importer`, `ls-skill-vetter`, `ls-skill-normalizer`, or `ls-skill-sandbox-tester`.

Do not use this skill for live OmniRoute proxy/model discovery; use `ls-omniroute-proxy`. Do not use it for OmniRoute administration; use `ls-omniroute-admin-automation`.

## Safety rules

- Default to read-only reporting. This first-pass update workflow must not create, modify, or delete converted OmniRoute skills.
- Treat upstream repository content as untrusted. Vet and sandbox any imported skill before activation.
- Do not trust a local skill as upstream-converted unless its `SKILL.md` frontmatter declares `extensions.omniroute.source_skill`.
- Treat `covered-native` rows as intentionally handled only when the native coverage map in `scripts/omniroute_update.py` and `../ls-omniroute/references/upstream-skill-coverage.md` both agree.
- Preserve repo-owned adapter content. Update reports are planning inputs, not permission to relocate or delete existing skill directories.
- Keep source metadata with every future converted skill so later checks can classify it deterministically.
- For normal Localsetup installations, never alter global Localsetup packages by default. If a converted or modified skill is needed, write a physical copy into the initiating repo's `ls/skills/` tree so the change is repo-scoped even when adapters are symlinked or skills are otherwise installed globally.
- This repo-scoped copy policy does not apply when maintaining the Localsetup framework source repository itself.
- Promotion from a repo-scoped skill copy to a machine/global Localsetup installation requires an explicit user choice.
- After a user creates or materially updates a repo-scoped skill copy, ask whether they want help opening a PR to the relevant upstream repository for consideration. If yes, ask for their preferred attribution string, such as a name, handle, email address, or other credit text.

## Source facts

- Upstream repository: `https://github.com/diegosouzapw/OmniRoute`
- Upstream skills root: `skills/`
- Authorized immutable source: OmniRoute `v3.8.48` at `7ee5bbc64dbb03e967521227f2afffeb7c9dad1e`
- Source tree: `4048504f76c6fb3dedd00ff2aa7250109308de99`
- Upstream skill inventory: `44` files under `skills/*/SKILL.md`
- Immutable inventory helper: `scripts/omniroute_inventory.py` derives skills, OpenAPI, routes, and `omniroute_*` tool receipts from the exact pinned Git object.
- Retained Localsetup claim references are a separate local input and require explicit `--localsetup-root`; neither the mirror root nor local claim root path is emitted.

Refresh these facts before a real import or update wave. Record the refreshed source in `references/source-ledger.md`. Treat the actual `skills/*/SKILL.md` inventory as authoritative when upstream prose has stale count text.

## Update report

Run the read-only check from the Localsetup checkout:

```bash
python3 ls/skills/ls-omniroute-update/scripts/omniroute_update.py check \
  --repo-root . \
  --source-repo https://github.com/diegosouzapw/OmniRoute.git \
  --ref 7ee5bbc64dbb03e967521227f2afffeb7c9dad1e \
  --output markdown
```

For offline checks, pass `--source-path` pointing at either an OmniRoute checkout or an exported `skills/` directory.

The report classifies rows as:

- `missing-local`: upstream skill exists, but no Localsetup-converted counterpart or consolidated native coverage declares matching support.
- `covered-native`: upstream skill is covered by one or more Localsetup-native OmniRoute skills in the consolidated coverage map.
- `current`: local converted skill source metadata matches upstream source hash and commit when commit data is available.
- `stale-local`: local converted skill exists, but upstream source hash or commit differs.
- `local-only`: local converted OmniRoute skill claims an upstream source skill that no longer exists.
- `untracked-local`: local OmniRoute-tagged skill exists but has no `extensions.omniroute.source_skill` metadata.
- `local-native`: local OmniRoute skill declares `extensions.omniroute.source_kind: localsetup-native` and is intentionally not tied to an upstream skill.

## Freshness validation

Use the freshness check when validating converted or consolidated OmniRoute skills against the upstream repository:

```bash
python3 ls/skills/ls-omniroute-update/scripts/omniroute_update.py freshness \
  --repo-root . \
  --source-repo https://github.com/diegosouzapw/OmniRoute.git \
  --ref 7ee5bbc64dbb03e967521227f2afffeb7c9dad1e \
  --output markdown
```

The freshness command exits `0` only when source-linked local converted skills are current and every required upstream skill is either converted or `covered-native`. By default, `stale-local` and `local-only` are blockers. Use `--strict-untracked` to also block on local OmniRoute skills without conversion metadata. Use `--require-all-upstream` when every upstream OmniRoute skill is expected to have converted or native Localsetup coverage.

## Expected converted metadata

Future converted skills should record this frontmatter shape:

```yaml
extensions:
  omniroute:
    source_kind: upstream-converted
    source_repo: https://github.com/diegosouzapw/OmniRoute
    source_path: skills/<skill>/SKILL.md
    source_ref: 7ee5bbc64dbb03e967521227f2afffeb7c9dad1e
    source_commit: <commit-sha>
    source_commit_date: <iso-date>
    source_sha256: <sha256-of-source-skill-md>
    source_skill: <upstream-skill-name>
    converted_at: <iso-date>
    converter_version: "1.0"
```

Localsetup-native OmniRoute skills should record this frontmatter shape instead:

```yaml
extensions:
  omniroute:
    source_kind: localsetup-native
    local_role: <main-router|proxy-discovery|admin-automation|update-workflow>
```

## Decision workflow

1. Run the update report against the desired upstream ref.
2. Run the freshness command before validating a converted or consolidated skill wave. Use `--require-all-upstream` when the task goal is complete coverage of upstream OmniRoute skills.
3. For `covered-native`, confirm the mapped native skill still covers the upstream operational area. If the upstream skill changed materially, update the native skill and coverage map.
4. For `missing-local`, decide whether the upstream skill should be covered by an existing native skill, a new native skill, or an imported converted skill. If importing, hand off to `ls-skill-importer`, then `ls-skill-vetter`, `ls-skill-normalizer`, and `ls-skill-sandbox-tester`.
5. For `stale-local`, inspect the upstream diff before changing anything. Treat this as an update proposal, not an automatic merge.
6. For `local-only`, confirm whether upstream removed or renamed the skill. Do not delete local content without an explicit repo-owner decision.
7. For `untracked-local`, decide whether the skill is intentionally Localsetup-native or should be linked to an upstream source. Add metadata only after confirming provenance.
8. For `local-native`, preserve the local skill unless the repo owner explicitly asks to remove or replace Localsetup-native behavior.
9. In a normal Localsetup installation, write any accepted import or modification as a physical repo-local skill under that repo's `ls/skills/`, even if the active adapter currently resolves skills from symlinks or global packages.
10. Ask whether the user wants to promote the repo-local skill copy to the global/machine Localsetup installation. Do not do this by default.
11. Ask whether the user wants help opening an upstream PR for consideration. If yes, collect their preferred attribution string before preparing the PR text.
12. Record the result and source evidence in the run ledger before making any skill changes.

## References

- `references/source-ledger.md`
- `references/update-workflow.md`
- `scripts/omniroute_update.py`

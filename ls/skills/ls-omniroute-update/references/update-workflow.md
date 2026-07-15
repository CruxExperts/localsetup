# Omni Route Update Workflow

## List Or Check

1. Run `scripts/omniroute_update.py check`.
2. Save Markdown or JSON output to the run ledger or a private maintenance path if the report is long.
3. Verify the source commit and source hash before using the report for import or update decisions.

## Freshness Check

Run `scripts/omniroute_update.py freshness` before validating any converted or consolidated OmniRoute skill wave against the upstream repository.

- Default blockers: `stale-local` and `local-only`.
- Add `--strict-untracked` when every local OmniRoute skill must declare conversion metadata.
- Add `--require-all-upstream` when the task requires every upstream OmniRoute skill to have converted or native Localsetup coverage.
- A non-zero exit means the skill set is not fresh enough for the chosen validation policy.

For consolidated native waves, use both `--require-all-upstream` and `--strict-untracked`. The expected healthy state for OmniRoute `v3.8.43` is 43 upstream skills reported as `covered-native` or `current`, the Localsetup-native OmniRoute skills reported as `local-native`, and zero `missing-local`, `stale-local`, `local-only`, or `untracked-local` rows.

## Import

1. Confirm the upstream skill is desired in Localsetup.
2. Use `ls-skill-importer` to obtain the upstream skill content.
3. Use `ls-skill-vetter` before trusting scripts, references, or instructions.
4. Use `ls-skill-normalizer` to adapt documentation and tooling to Localsetup conventions.
5. Use `ls-skill-sandbox-tester` before registering or deploying the converted skill.
6. In a normal Localsetup installation, write the converted result as a physical repo-local copy under the initiating repo's `ls/skills/`. Do not modify global Localsetup packages by default, even when the active adapter uses symlinks or global skill packages.
7. Add `extensions.omniroute` metadata to the converted skill frontmatter.
8. Register the converted skill through the standard Localsetup skill registration process for that repo.
9. Ask whether the user wants to promote the repo-local skill copy to the machine/global Localsetup installation. This requires explicit approval.
10. Ask whether the user wants help opening a PR upstream for consideration. If yes, collect a preferred attribution string, such as a name, handle, email address, or other credit text.

## Strict Replacement

Use strict replacement only when the maintainer explicitly wants Localsetup to mirror the current upstream skill set and remove older converted entry points.

1. Verify the upstream commit, tag, package version, and actual `skills/*/SKILL.md` count from primary sources.
2. Run the importer scan when the validation pattern file is fresh. If the scanner blocks on stale pattern metadata and no non-mutating use-existing path is available, record that blocker and perform a static vetting pass instead.
3. Delete only local skills whose frontmatter declares `extensions.omniroute.source_kind: upstream-converted`. Do not glob-delete OmniRoute-named directories.
4. Preserve all `extensions.omniroute.source_kind: localsetup-native` skills.
5. Generate each converted skill from the pinned upstream `SKILL.md` with complete `extensions.omniroute` provenance and Localsetup safety wording before source-derived commands.
6. Update `pack.yaml`, smoke-command metadata, tests, source ledger, generated docs, and aliases in the same wave.
7. Validate with strict freshness, catalog checks, focused updater/manifest tests, native helper help commands, generated-doc drift checks, and final suite checks proportionate to the surface changed.

## Consolidated Native Coverage

Use consolidated native coverage when the maintainer wants a smaller, better-routed Localsetup pack instead of one Localsetup skill per upstream OmniRoute skill.

1. Verify the upstream commit, tag, package version, and actual `skills/*/SKILL.md` count from primary sources.
2. Group upstream skills by Localsetup operator workflow, not by upstream folder prefix alone.
3. Keep each native skill narrow enough to route accurately but broad enough to cover the related API/CLI surface.
4. Update the human coverage map in `../ls-omniroute/references/upstream-skill-coverage.md`.
5. Update the machine coverage map in `scripts/omniroute_update.py`.
6. Remove converted package registrations and taxonomy rows after preserving source provenance in the ledger.
7. Validate with `freshness --require-all-upstream --strict-untracked`, catalog checks, focused updater/manifest/API helper tests, generated-doc drift checks, and final suite checks proportionate to the surface changed.

## Update

1. Treat `stale-local` as an update proposal.
2. Inspect the upstream diff from the local metadata commit to the target source commit.
3. Vet new or changed scripts and instructions before merging.
4. Preserve Localsetup-specific safety, path, and testing adjustments unless the maintainer explicitly chooses otherwise.
5. In a normal Localsetup installation, apply the accepted update to the repo-local physical skill copy, not to global Localsetup packages.
6. Update `extensions.omniroute` metadata only after the converted content reflects the verified source.
7. Offer explicit global promotion and upstream PR assistance as separate follow-up choices.

## Modify

Localsetup-specific changes may be appropriate after conversion, but keep the provenance clear:

- Preserve upstream source metadata.
- Explain the Localsetup-specific delta in the skill body or a reference when it affects behavior.
- Do not present modified content as a byte-for-byte upstream copy.
- In normal Localsetup installations, make the modified version repo-local first. The user may later choose to promote it globally or submit it upstream.

## Scope Boundary

The repo-local physical-copy rule applies to Localsetup installations that consume the framework. It does not apply when the task is maintenance of the Localsetup framework source repository itself; in that case, changes belong in the framework source tree and follow the repository's normal validation and publishing workflow.

## Remove

1. Confirm whether upstream removed, renamed, or replaced the source skill.
2. Confirm whether Localsetup still needs the converted skill independently.
3. Record the repo-owner decision in the run ledger.
4. Remove registration and files only after explicit approval and validation.

## Status Handling

- `missing-local`: candidate import.
- `covered-native`: upstream skill is covered by a consolidated Localsetup-native skill.
- `current`: no import/update action needed.
- `stale-local`: candidate update after diff review.
- `local-only`: candidate removal, rename handling, or Localsetup-native preservation.
- `untracked-local`: candidate metadata repair or intentional Localsetup-native classification.

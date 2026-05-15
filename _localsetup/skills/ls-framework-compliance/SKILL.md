---
name: ls-framework-compliance
description: "Pre-task workflow, certainty assessment, context load, document status, testing, Git checkpoints, document maintenance. Use for framework modifications, PRDs, or any task that must follow checklist and checkpoints."
metadata:
  version: "1.2"
---

# Framework Compliance

Use this skill when a task affects Localsetup framework behavior, shipped skills, installer/runtime rules, repo documentation, PRDs, or any workflow where rule compliance and traceability matter.

## Pre-Task Flow

Before changing files:

1. Identify the task type: documentation, skill, framework code, installer, tests, git operation, PRD/queue work, or release workflow.
2. Load the active repo context from the repository instructions and the relevant documents under `_localsetup/docs/`.
3. Run or request the context check when framework state is uncertain:

```bash
./_localsetup/tools/verify_context
```

4. Check core constraints before acting: repo/data separation, user-owned worktree edits, secret/private state exclusion, platform compatibility, and required tests.
5. Assess certainty. If the active docs do not answer a core-rule question, pause for clarification before making a risky change.

## Current Sources Of Truth

Use active v3 sources only:

- Owning skills and workflow packages for operational behavior. Public docs carry `owner_skill` or `owner_package` frontmatter so agents know what to load.
- `_localsetup/docs/AGENTIC_DESIGN_INDEX.md` for agent-facing design and workflow doc navigation.
- `_localsetup/docs/WORKFLOW_REGISTRY.md` for named workflows and their triggers.
- `_localsetup/docs/DOCUMENT_LIFECYCLE_MANAGEMENT.md` for document status meanings and ownership metadata.
- `_localsetup/docs/SKILLS_AND_RULES.md` and `_localsetup/docs/AGENT_SKILLS_COMPLIANCE.md` as public references for skill format and loading rules; `ls-skill-creator` and `ls-task-skill-matcher` own execution behavior.
- `_localsetup/docs/REPO_AND_DATA_SEPARATION.md` as the public reference for framework source versus repo-local data boundaries; this skill owns the operational guardrail.
- `_localsetup/docs/QUICKSTART.md` for supported verification commands.
- `_localsetup/config/platforms.yaml` and `_localsetup/docs/PLATFORM_REGISTRY.md` for supported platform paths.
- `_localsetup/config/pack.yaml` for pack membership and `extensions.skill_taxonomy`; generated catalogs must not invent their own classification.

Do not reference removed v2/v3-draft helper files or indexes. In particular, do not call missing rule-enforcer or document-maintenance shell helpers, and do not rely on non-existent YAML document/rule indexes.

## Document Status Check

Before relying on a framework document:

1. Open the actual Markdown file under `_localsetup/docs/`.
2. Read its YAML frontmatter.
3. Treat `status: ACTIVE` as current guidance.
4. Treat `status: PROPOSAL`, `DRAFT`, `DEPRECATED`, or `ARCHIVED` as non-authoritative unless the user explicitly asks you to work from it.
5. For active public framework docs, read `owner_skill` or `owner_package` and load that owner for operational rules before changing behavior.
6. If `status:` or ownership is missing, treat the document as uncertain and cross-check against an active index or ask before relying on it for core behavior.
7. When adding or materially changing a framework doc, include `status:`, `version:`, and the appropriate owner field.

The status meanings are defined in [DOCUMENT_LIFECYCLE_MANAGEMENT.md](../../docs/DOCUMENT_LIFECYCLE_MANAGEMENT.md).

## Implementation Guardrails

- Preserve unrelated work. If the worktree is dirty, identify your owned files and do not revert edits made by others.
- Keep framework source in `_localsetup/`; do not put generated private state, local secrets, or machine-specific agent data into tracked files.
- For skill changes, keep `SKILL.md` Agent Skills compatible with `name` and `description` frontmatter, and keep auxiliary files scoped to the skill directory.
- Prefer the repo's active Python and shell tooling over ad hoc helpers.
- Use relative links for repo docs and verify they still resolve.
- For PRD or workflow queue work, update status/outcome fields only in the relevant active queue or PRD files.

## Verification

Choose checks based on the surface changed:

```bash
./_localsetup/tools/verify_context
./_localsetup/tools/verify_rules
python3 _localsetup/tools/localsetup_v3.py --source-root . validate-catalog
python3 _localsetup/tools/localsetup_v3.py --source-root . scan-migration
python3 _localsetup/tools/localsetup_v3.py --source-root . audit-global-first
./_localsetup/tests/automated_test.sh
python3 -m pytest _localsetup/tests
git diff --check
```

- Run `verify_context` when validating that the framework context is present.
- Run `verify_rules` after framework or rule-related changes.
- Run `validate-catalog` after skill, catalog, platform, or registry changes.
- Run `scan-migration` when migration, installer, adapter, generated-artifact, or source-boundary behavior may be affected.
- Run `audit-global-first` when global-first layout, lockfile, target-state, PowerShell removal, or source/target docs claims may be affected.
- Run focused tests for narrow changes; run the full smoke and pytest suites before release or broad framework changes.

## Git And Handoff

- Create commits only when the user asked for commits or the workflow explicitly requires a checkpoint.
- Use Conventional Commit style for normal commits.
- Never stage broad unrelated work from a dirty worktree.
- In the final handoff, report changed files, checks run and results, and any residual risk or skipped checks.

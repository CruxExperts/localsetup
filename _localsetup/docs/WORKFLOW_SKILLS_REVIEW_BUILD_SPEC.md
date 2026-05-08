---
status: ACTIVE
version: 3.0
last_updated: "2026-03-09"
---

# Workflow and skills review (build spec)

## How to use this doc

1. Read **Constraints** and **Build sequence** first.
2. Implement **Build sequence** in step order; each step lists inputs and outputs.
3. Run **Verification gate** last; required audit must pass or findings triaged before done.
4. **Canonical mapping** is the source for Workflow ID, display name, and aliases when editing [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) and the quick-ref file.

**Audience:** Maintainers and agents executing the review.  
**Scope:** Framework repo only.  
**Overrides:** A PRD may override this spec; otherwise this is the build contract.

---

## Constraints (locked decisions)

| # | Topic | Decision |
|---|--------|----------|
| 1 | Scope | Framework repo only; publish/release steps in scripts/ and docs/WORKFLOW_INDEX.md. |
| 2 | Artifacts | WORKFLOW_REGISTRY update + exactly one quick-ref file under `_localsetup/docs/`. |
| 3 | Renaming | Workflow ID + display name + aliases in registry and quick-ref; no repo-wide grep rewrites. |
| 4 | Normalize | Mandatory after import per [SKILL_IMPORTING.md](SKILL_IMPORTING.md); `_localsetup/skills/localsetup-skill-importer/SKILL.md` must match. |
| 5 | Pipelines (pass 1) | Only skill onboarding + pre-publish; server/PR pipelines deferred. |
| 6 | Umbrella | Registry is source for framework-wide umbrellas; [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md) links here only. If no framework-wide umbrella names are shipped, state that explicitly in the registry (repo-local names live in `.agent/` / PRD only). |
| 7 | Non-ACTIVE docs | Registry Usage section lists PROPOSAL/DEFERRED agent-facing docs (inventory process below). |
| 8 | Gate | `run_framework_audit.py --output <path>` required before done. |

---

## Canonical workflow mapping

Use this table when adding **Workflow ID**, **Display name**, and **Aliases** columns to WORKFLOW_REGISTRY. Rows follow the current registry order. Skill IDs are unchanged this pass.

| Workflow ID | Display name | Aliases | Skill(s) | Impact review |
|-------------|--------------|---------|----------|---------------|
| `spec-clarify-reverse` | Reverse prompt (spec clarify) | decision tree, reverse prompt | `localsetup-decision-tree-workflow` | No |
| `queue-batch-implement` | Queue batch (implement PRDs) | Agent Q queue, process PRDs | `localsetup-agentic-prd-batch` | Yes if destructive |
| `transport-handoff` | Agent handoff (mail/file_drop) | Agent Q bidirectional | `localsetup-agentq-transport`, `localsetup-mail-protocol-control` (strict mail) | Yes if destructive ship |
| `umbrella-run` | Umbrella run (multi-phase) | umbrella workflow | `localsetup-agentic-umbrella-queue` | Yes for big/destructive |
| `ops-guarded` | Guarded ops (sudo/HITL) | lazy admin, manual execution | `localsetup-framework-compliance`; tmux ops requires `localsetup-tmux-shared-session-workflow` | No |
| `ops-tmux-session` | Tmux ops session | tmux shared session | `localsetup-tmux-shared-session-workflow` | No |
| `audit-framework` | Framework audit | run audit | `localsetup-framework-audit` | No |
| `skills-index-refresh` | Skill index refresh + scrub | refresh skills, scrub index | `localsetup-skill-discovery` | No |
| `tmux-terminal-mode` | Tmux terminal mode | tmux terminal mode | (tool only) `_localsetup/tools/tmux_terminal_mode` | No |

**Release pointer:** After `audit-framework`, release steps are in `docs/WORKFLOW_INDEX.md` and `scripts/publish`.

---

## Pipelines (pass 1 only)

| Pipeline ID | Display name | Steps (in order) | After last step |
|-------------|--------------|------------------|-----------------|
| `pipeline-skill-onboard` | Skill onboarding | `localsetup-skill-vetter` (optional) → `localsetup-skill-importer` → `localsetup-skill-normalizer` → `localsetup-skill-sandbox-tester`; optional `localsetup-framework-audit` | N/A |
| `pipeline-pre-publish` | Pre-publish | `localsetup-github-publishing-workflow` → `localsetup-automatic-versioning` → `localsetup-framework-audit` | Release automation in scripts/ |
| `pipeline-pr-feedback-loop` | PR feedback improvement loop | `localsetup-receiving-code-review` → `localsetup-tdd-guide` (or `localsetup-test-runner` where tests already exist) → `localsetup-pr-reviewer` | N/A |
| `pipeline-git-repair-hygiene` | Git repair and hygiene | `localsetup-unfuck-my-git-state` → `localsetup-git-workflows` → `localsetup-framework-compliance` | N/A |
| `pipeline-server-triage-patch` | Server triage and patch | `localsetup-system-info` → `localsetup-linux-service-triage` → `localsetup-linux-patcher` | Ops-only; apply PHC before patching hosts. |
| `pipeline-repo-polish` | Repo polish (docs + scripts) | `localsetup-script-and-docs-quality` → `localsetup-humanizer` → `localsetup-github-publishing-workflow` | For \"make this repo presentable\" even when not doing full public release. |

**PHC (pre-human confirmation) for pipelines**

- **pipeline-skill-onboard:** Before `localsetup-skill-importer` writes into `_localsetup/skills/`, present impact summary and get explicit confirmation (destructive overwrite, merge, replace). Use `localsetup-agentic-umbrella-queue` / impact-review habit; importer already lists duplicate/overlap options.
- **pipeline-pre-publish:** Before any irreversible scrub or publish commit, confirm scope (files touched, secrets/PII). Use `localsetup-framework-compliance` pre-task flow where applicable.

**Normalizer step vs mandatory normalize on import**

- After step 1, importer aligns with SKILL_IMPORTING: normalize is mandatory before copy when importing. **`localsetup-skill-normalizer` in the pipeline then means:** batch-normalize skills already in the tree that were imported without normalize, or run Phase 2 tooling normalization; **skip** the normalizer step when the importer just normalized on import and no legacy dirs need a pass.

**Deferred (pass 2):** `pipeline-server-routing`, `pipeline-pr-lifecycle` — do not add to registry until pass 1 IDs are stable.

---

## Quick-ref file requirements

Create `_localsetup/docs/WORKFLOW_QUICK_REF.md` (preferred) in the **same change set** as registry edits so nothing links to a missing file.

**Content:**

1. **Workflow rows:** Copy from canonical mapping: Workflow ID, display name, aliases, skill(s), one canonical doc link per row.
2. **Invoke by alias:** Short section listing common user phrases mapped to Workflow ID (so agents match legacy prompts without grep rewrites).
3. **Publish workflow row:**

   | Workflow ID | Display name | Aliases | Skill(s) | Doc / note |
   |-------------|--------------|---------|----------|------------|
   | `publish` | Publish workflow | publish, version bump, release | N/A | Procedure in `docs/WORKFLOW_INDEX.md` and `scripts/publish`. |

4. **Capabilities without a registry row (optional appendix):** Table or bullet list of high-traffic skills that stay capability-only (e.g. `localsetup-npm-management`, `localsetup-cloudflare-dns`, `localsetup-mail-protocol-control` when not doing strict handoff) so agents do not assume every skill needs a workflow row. Reduces false “missing workflow” reports.

---

## Build sequence

Execute in order. Skip only when a step is already satisfied.

| Step | Action | Input | Output |
|------|--------|-------|--------|
| 1 | Align skill-importer with mandatory normalization | [SKILL_IMPORTING.md](SKILL_IMPORTING.md) step 6b | Updated `_localsetup/skills/localsetup-skill-importer/SKILL.md`. **Deploy:** use [MULTI_PLATFORM_INSTALL.md](MULTI_PLATFORM_INSTALL.md) or your repo’s deploy entrypoint so `.agents/skills/` and compatibility platform paths match `_localsetup/skills/` after edit. |
| 2 | Create quick-ref file | Canonical mapping + pipelines + Quick-ref requirements | `WORKFLOW_QUICK_REF.md` (or `WORKFLOW_IDS.md`) — must exist before step 5 links it. |
| 2b | Optional: skill/workflow matrix | [SKILLS.md](SKILLS.md) or `_localsetup/skills/*/SKILL.md` list | `WORKFLOW_SKILL_MATRIX.md` (or appendix inside quick-ref): skill ID, registry row yes/no, pipeline step yes/no — makes gaps visible without requiring every skill to have a row. |
| 3 | Refactor WORKFLOW_REGISTRY | Canonical mapping; move long commands to SKILL_DISCOVERY | Registry table with ID/display/aliases; shortened cells; Pipelines section; Umbrella subsection or explicit “no framework-wide umbrella names”; Usage footnote from Non-ACTIVE inventory. |
| 4 | Update umbrella doc | Registry as source | [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md): pointer to registry; repo-local names in `.agent/` / PRD only if no framework list shipped. |
| 5 | Link quick-ref from index + context | Quick-ref path | [AGENTIC_DESIGN_INDEX.md](AGENTIC_DESIGN_INDEX.md) Core docs or Quick reference. **Master rule:** add one line under Key files in `.cursor/rules/localsetup-context.mdc`: Workflow IDs and aliases live in `WORKFLOW_QUICK_REF.md` (and WORKFLOW_REGISTRY), so always-loaded context stays small without duplicating the full table. |
| 6 | Regenerate skills catalog | Any change under `_localsetup/skills/*/SKILL.md` | [SKILLS.md](SKILLS.md) per framework procedure. **If adding a new skill:** extend `_localsetup/tests/skill_smoke_commands.yaml` in the same PR when the skill has runnable tooling (audit uses this list). |
| 7 | Optional: Workflow ID in decision tree doc | Canonical mapping | Under H1 in [DECISION_TREE_WORKFLOW.md](DECISION_TREE_WORKFLOW.md), add one line: `Workflow ID: spec-clarify-reverse` — aligns search and agents without renaming the file or breaking links. |

---

## Verification gate

**Required**

```bash
python _localsetup/skills/localsetup-framework-audit/scripts/run_framework_audit.py --output /path/to/report.md
```

- Triage or fix reported issues; do not silently ignore.

**Recommended (after touching rules, registry, or cross-platform paths)**

```bash
./_localsetup/tools/verify_context
./_localsetup/tests/automated_test.sh
```

- Not blocking by contract; run when feasible to catch regressions.

**Outcome / traceability**

- If this pass produces an outcome or PRD update, attach git hash per [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md).

---

## Non-ACTIVE docs inventory (registry Usage footnote)

**Goal:** Registry Usage section must list agent-facing docs that are not ACTIVE so agents check `status` before following.

**Process**

1. Traverse `_localsetup/docs/**/*.md` (and agentic subpaths) and read YAML frontmatter `status:`.
2. For every doc with `PROPOSAL`, `DRAFT`, or partial DEFERRED scope, add a row: doc link, status, one-line note (what not to assume).
3. Optional: script that prints markdown rows for copy-paste into WORKFLOW_REGISTRY.

**Starter row (keep and extend)**

| Doc | Status | Note |
|-----|--------|------|
| [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) | ACTIVE | Part 19 = backlog; deferred list in DEFERRED.md — do not treat Part 19 as shipped until spec says so |

See [DOCUMENT_LIFECYCLE_MANAGEMENT.md](DOCUMENT_LIFECYCLE_MANAGEMENT.md) for status meanings.

---

## References

| Doc | Use |
|-----|-----|
| [WORKFLOW_REGISTRY.md](WORKFLOW_REGISTRY.md) | Target for step 3 |
| [MULTI_PLATFORM_INSTALL.md](MULTI_PLATFORM_INSTALL.md) | Deploy after editing `_localsetup/skills/` |
| [SKILL_IMPORTING.md](SKILL_IMPORTING.md) | Mandatory normalize policy |
| [SKILL_NORMALIZATION.md](SKILL_NORMALIZATION.md) | Normalize rules |
| [SKILL_DISCOVERY.md](SKILL_DISCOVERY.md) | Refresh/scrub commands (move out of registry cells) |
| [AGENTIC_UMBRELLA_WORKFLOWS.md](AGENTIC_UMBRELLA_WORKFLOWS.md) | Target for step 4 |
| [GIT_TRACEABILITY.md](GIT_TRACEABILITY.md) | Hash on outcome |
| Maintainer repo | `docs/WORKFLOW_INDEX.md` — pointer only |

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

---
name: ls-skill-creator
description: "Use when creating a new Agent Skills-compliant skill, adapting a document into a skill, importing an existing skill for Localsetup, or exporting framework skills to other spec-compliant hosts."
metadata:
  version: "1.3"
---

# Skill creator (framework)

**Purpose:** Create or import skills that are **fully [Agent Skills](https://agentskills.io/specification)-compliant** and work in this framework and in any spec-compliant host (e.g. [Anthropic's skills](https://github.com/anthropics/skills)). Turn user descriptions, docs, or existing skills (from Anthropic or elsewhere) into framework-registered skills; or guide exporting our skills for use elsewhere. Skills are interchangeable because the format follows the spec, so they can be borrowed and reused across ecosystems.

## When to use this skill

- User wants to "create a new skill," "capture this as a skill," or "turn this into a skill."
- User wants to **import** an existing skill, such as one from Anthropic's repo, into this framework so it is normalized, registered, and deployed.
- User provides a skill or document from elsewhere and wants it adapted for this framework.
- User asks about using framework skills in another host or making skills interchangeable.

## Interoperability (design for interchange)

- **Our output is spec-compliant.** Every skill we create or adapt conforms to the [Agent Skills](https://agentskills.io/specification) spec (required `name`, `description`; optional `metadata.version`, `scripts/`, `references/`, `assets/`). No framework-only required fields are added, so the skill can be copied into any Agent Skills host.
- **External skills can be used here.** A skill from [anthropics/skills](https://github.com/anthropics/skills) or any spec-compliant source can be copied into `ls/skills/`, optionally renamed to `ls-*`, given `metadata.version` if missing, and registered. Preserve imported content as-is during the copy step, then immediately hand off to `ls-skill-normalizer` so document and tooling normalization follow [SKILL_NORMALIZATION.md](../../docs/SKILL_NORMALIZATION.md).
- **Design guidance:** For structure, progressive disclosure, and what to include (scripts, references, assets), follow the [Agent Skills spec](https://agentskills.io/specification) and [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator). This skill adds framework placement and registration; the resulting skill remains portable. See [SKILL_INTEROPERABILITY.md](../../docs/SKILL_INTEROPERABILITY.md).

## Rule ownership

This skill owns framework skill-authoring and interoperability behavior. Public docs such as `AGENT_SKILLS_COMPLIANCE.md`, `SKILL_INTEROPERABILITY.md`, and `SKILLS_AND_RULES.md` are reference surfaces; do not add new required `SKILL.md` fields there without also updating this skill, validation tests, and generated catalogs.

- Keep Agent Skills portability: `name` and `description` remain the only required skill frontmatter fields.
- Keep Localsetup-only classification in `ls/config/pack.yaml` under `extensions.skill_taxonomy`; do not require taxonomy fields in every `SKILL.md`.
- For imports, hand off to `ls-skill-importer`, `ls-skill-vetter`, `ls-skill-normalizer`, and `ls-skill-sandbox-tester` rather than embedding their whole workflows here.

## Inputs you can accept

1. **Free-form description**  - User describes the workflow or behavior. Infer purpose, steps, and trigger scenarios; ask one or two clarifying questions if needed. Draft a spec-compliant skill (use Anthropic's design principles: concise, degrees of freedom, progressive disclosure).
2. **Existing document**  - Markdown file path, GitHub URL, or pasted content. Extract purpose, steps, and key rules; normalize to third person and framework style; keep spec-compliant structure. When the source is pasted content or a URL to a single document, follow [SKILL_IMPORTING.md "Adding a skill from paste or URL"](../../docs/SKILL_IMPORTING.md#adding-a-skill-from-paste-or-url): write the content to a temporary directory first, run the validation script on that path, present content-safety results and user choices, and only then copy to `ls/skills/` if the user approves. Do not write pasted or single-doc content directly to the final skill location without validation.
3. **Existing skill (import)**  - Directory or URL of a skill, such as one from Anthropic's repo. Copy the approved skill into `ls/skills/` without altering its body or optional directories; ensure `name` matches the directory name and add `metadata.version: "1.0"` if missing. Then load `ls-skill-normalizer` and run the normalizer workflow against the copied skill before registration or deploy.

## Framework skill requirements (spec-compliant)

- **Spec:** Every skill must satisfy the [Agent Skills](https://agentskills.io/specification) spec so it remains usable in any spec-compliant host. Required: `name` (matches directory, 1-64 chars, lowercase, hyphens), `description` (1-1024 chars, what + when to use). Optional: `metadata.version`, `license`, `compatibility`; optional dirs: `scripts/`, `references/`, `assets/`.
- **Name (framework convention):** `ls-<kebab-case>` when the skill lives in this framework; directory name must equal `name` per spec.
- **Location (source):** `ls/skills/<name>/SKILL.md`. This is the canonical skill; deploy maps to each platform's configured adapter skills root per [ls/docs/PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) and `ls/config/platforms.yaml`.
- **Frontmatter:** `name`, `description` (required). Include `metadata.version: "1.0"` so our hook can auto-bump; description must state what the skill does and **when to use it** (trigger terms). Third person.
- **Body:** Start with a **Purpose** line; clear sections (##). Keep under ~500 lines; use progressive disclosure; link to `references/` or `ls/docs/` as needed. Follow [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) for structure and what to put in scripts/references/assets so the skill stays portable.

## Registration (required for discoverability)

After creating the skill, **register it** in every place that lists framework skills so it appears in each platform's context and can be loaded when the task matches. Add one row or bullet per skill with a short "When to use" line.

**Canonical list of files to update:** Read [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md), section **"Skill registration (new skills)"**. That table lists every file (per platform and shared) that must include the new skill. Update every file listed there. Do not maintain a separate list in this skill; the registry is the source of truth so that when new platforms are added, registration stays complete.

Use the same "When to use" phrasing across all files so indexes stay consistent.

## Workflow (agent steps)

**If importing an existing skill (e.g. from Anthropic):**

1. **Obtain**  - Get the skill directory (clone, download, or path). Ensure it has `SKILL.md` and optional `scripts/`, `references/`, `assets/` per spec.
2. **Duplicate, overlap, and namespace check**  - List existing skills from `ls/skills/` (dir names and each SKILL.md `name` + `description`). Compare the candidate: **Namespace collision** = same `name` or directory already exists; **High overlap** = very similar description/purpose/triggers. If either: warn and offer **Keep existing** (do nothing, skip import), **Replace existing** (overwrite with new), **Merge** (combine best of both into one skill), **Create as new** (use a different name, e.g. `ls-<name>-previous`). Get explicit user choice; do not auto-replace or auto-merge.
3. **Copy as-is**  - Place the approved candidate under `ls/skills/<name>/` (or chosen name after Merge/Create as new). If adopting framework convention, use `ls-<name>` and set `name: ls-<name>` in frontmatter. Do not edit the body, references, scripts, or assets during this copy step.
4. **Add metadata.version if missing**  - Ensure `metadata.version: "1.0"` (or current) in frontmatter so our versioning hook works.
5. **Hand off to normalizer**  - Load `ls-skill-normalizer` and run the copied skill through [SKILL_NORMALIZATION.md](../../docs/SKILL_NORMALIZATION.md): Phase 1 document normalization, then Phase 2 tooling normalization unless the user explicitly chooses the keep-original-tooling exception.
6. **Register**  - After normalization is complete, add the skill and a short "When to use" line to every file in [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) under "Skill registration (new skills)."
7. **Confirm**  - Tell the user the skill is imported, normalized, and registered; they can run deploy.

**If creating from scratch or from a doc:**

1. **Gather input**  - User description, document path/URL, or pasted content. If from a doc, read or fetch it.
2. **Decide name and triggers**  - Propose `ls-<name>` and "When to use" (trigger scenarios). Confirm if ambiguous.
3. **Public skill discovery (recommended)**  - Load **ls-skill-discovery**: read PUBLIC_SKILL_REGISTRY.urls and PUBLIC_SKILL_INDEX.yaml (refresh index if empty/stale), match the proposed purpose/description to public skills, return top 5 similar. Present: "Similar public skills exist: [list]. Options: (1) In-depth summary of each, (2) Use a public skill (pull and run through import), (3) Continue on your own, (4) Adapt from one." If user chooses (2) or (4), run skill-importer for the chosen skill; then for (4) help adapt. If (3), proceed to step 4.
4. **Duplicate, overlap, and namespace check**  - List existing skills from `ls/skills/` (dir names and each SKILL.md `name` + `description`). If the proposed name already exists (**namespace collision**) or an existing skill has very similar purpose/triggers (**high overlap**): warn and offer **Keep existing** (do nothing, do not create), **Replace existing** (overwrite that skill with the new content), **Merge** (combine best of both into one skill), **Create as new** (use a different name). Get explicit user choice.
5. **Draft SKILL.md**  - Spec-compliant frontmatter and body (Purpose, sections). Use [Agent Skills spec](https://agentskills.io/specification) and [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator) for structure; keep body portable (no framework-only requirements in content).
6. **Create file**  - Write `ls/skills/<name>/SKILL.md` (or chosen name). Deploy will copy to each platform's configured adapter skills root (see PLATFORM_REGISTRY and `ls/config/platforms.yaml`); or copy manually to the adapter path if needed.
7. **Register**  - Add to every file in [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) under "Skill registration (new skills)."
8. **Confirm**  - Skill is created, spec-compliant, and registered; user can run deploy. Skill can be reused in other Agent Skills hosts by copying the directory.

## Duplicate and overlap (user options)

- Before creating or importing, check existing `ls/skills/` (names and descriptions). On **namespace collision** (same name/dir) or **high overlap** (very similar purpose): warn and offer **Keep existing**, **Replace existing**, **Merge** (best of both), **Create as new** (different name). User choice is final.

## Quality checks

- Skill is [Agent Skills](https://agentskills.io/specification)-compliant: `name` matches directory, `description` present and under 1024 chars; optional dirs follow spec.
- For framework use: name follows `ls-*` convention; `metadata.version` present; registration complete per PLATFORM_REGISTRY.
- Description includes what the skill does and when to apply it (trigger terms). Body has clear sections; no PII or machine-specific paths in committed content.
- All registration files from [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) are updated so the skill appears in every platform index.

## Using our skills in another host (export)

- Copy the skill directory from `ls/skills/<name>/` (or from your platform's deployed adapter path listed in [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) and `ls/config/platforms.yaml`). It is a valid Agent Skills skill; use it in any spec-compliant host without changes. Optionally rename directory and `name` to match the host's conventions. See [SKILL_INTEROPERABILITY.md](../../docs/SKILL_INTEROPERABILITY.md).

## Reference

- [Agent Skills specification](https://agentskills.io/specification)  - Format and interchange.
- [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)  - Design, anatomy (scripts/references/assets), progressive disclosure.
- [SKILL_INTEROPERABILITY.md](../../docs/SKILL_INTEROPERABILITY.md)  - Import external skills; export our skills; full interchange steps.
- [SKILL_DISCOVERY.md](../../docs/SKILL_DISCOVERY.md)  - Public registries and discovery; use ls-skill-discovery when creating to recommend similar public skills.
- [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md)  - Registration file list.
- [SKILLS_AND_RULES.md](../../docs/SKILLS_AND_RULES.md)  - How skills are loaded and platform paths.

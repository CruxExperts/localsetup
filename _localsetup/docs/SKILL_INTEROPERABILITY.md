---
status: ACTIVE
version: 3.0
---

# Skill interoperability (Localsetup v3)

**Purpose:** Framework skills are [Agent Skills](https://agentskills.io/specification)-compliant so they can be used in any spec-compliant host. External skills (e.g. from [Anthropic's skills](https://github.com/anthropics/skills)) can be used in this framework with minimal adaptation. Skills are interchangeable across ecosystems that follow the same spec.

## Interoperability principle

- **Our skills** use only the Agent Skills spec: required `name` and `description`, optional `metadata.version`, optional `license` / `compatibility`. Directory layout is `SKILL.md` plus optional `scripts/`, `references/`, `assets/`. No framework-only required fields. They are valid Agent Skills and can be copied into another host (e.g. Claude Code, Anthropic's skills repo) as-is; the `ls-*` name is a convention, not a spec requirement.
- **External skills** that comply with the Agent Skills spec can be used in this framework by copying them into `_localsetup/skills/`, optionally renaming to `ls-*` for consistency, adding `metadata.version` if missing, and registering them in our platform indexes (see below). No change to the skill body or structure is required for spec compliance.
- **Workflow packages** under `_localsetup/workflows/ls-workflow-*` are executable Agent Skills packages because they include `SKILL.md`. Their `workflow.yaml` metadata is Localsetup-specific and is used for workflow validation, pack selection, generated registries, and install dependency inclusion.

## Using an external skill in this framework (import)

1. **Obtain the skill**  - Clone or download a spec-compliant skill (e.g. from [anthropics/skills](https://github.com/anthropics/skills)) so you have a directory containing `SKILL.md` and any optional `scripts/`, `references/`, `assets/`.
2. **Copy into the framework**  - Place it under `_localsetup/skills/<skill-name>/`. If you want it to follow our naming convention, use `_localsetup/skills/ls-<name>/` and set `name: ls-<name>` in the frontmatter (directory name must match `name` per spec).
3. **Add metadata.version if missing**  - Ensure frontmatter includes `metadata.version: "1.0"` (or any string) so our versioning hook can bump it. The spec allows optional `metadata`; we use it for document versioning.
4. **Register**  - Add the skill to every file listed in [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md) under "Skill registration (new skills)" so it appears in each platform's context index. Use a short "When to use" line consistent with the skill's `description`.
5. **Deploy**  - Run deploy (or rely on existing deploy) so platform-specific paths get the new skill. The skill content is already spec-compliant; no body changes are required for interoperability.

## Using a framework skill elsewhere (export)

- **Copy the skill directory**  - Use `_localsetup/skills/<name>/` as source. After v3 install, managed copies live in `~/.local/share/agents/skills/localsetup`, and platform adapter paths such as `.cursor/skills/<name>` or `.codex/skills/<name>` attach to that library by symlink or portable copy.
- **Use in any Agent Skills host**  - The directory is a valid Agent Skills skill. The host only needs to support the [Agent Skills](https://agentskills.io/specification) format (SKILL.md with `name` and `description`, optional dirs). No need to change the skill; `ls-*` is a naming choice and does not affect spec validity.
- **Optional**  - If the target host expects a different name, rename the directory and the `name` field so they match (spec requirement). Paths inside the skill (e.g. `_localsetup/docs/...`) may be framework-specific; the host can ignore or map them as needed.

## Using a workflow package elsewhere

Workflow packages can be copied to another Agent Skills-compatible host as executable `SKILL.md` packages, but only Localsetup understands the full `workflow.yaml` contract.

- Copy `_localsetup/workflows/<name>/` when you want the workflow instructions plus metadata.
- Copy only the `SKILL.md` package content when the target host only needs executable instructions.
- Preserve the directory name and `name` field match.
- Treat `workflow.yaml` as advisory metadata outside Localsetup unless the target host has explicit support for it.

## Specification and design references

- **Format (required for interchange):** [Agent Skills specification](https://agentskills.io/specification)  - [agentskills/agentskills](https://github.com/agentskills/agentskills).
- **Design and authoring:** [Anthropic's skill-creator](https://github.com/anthropics/skills/tree/main/skills/skill-creator)  - principles (concise, degrees of freedom), anatomy (scripts/references/assets), progressive disclosure, what to include/avoid. Our skill-creator adds framework placement and registration; for structure and content design, follow the Agent Skills spec and Anthropic's guidance so skills remain portable.
- **Validation:** [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref)  - `agentskills validate path/to/skill` to check frontmatter and naming.

## Summary

| Direction | Action |
|-----------|--------|
| **External -> Framework** | Copy skill dir into `_localsetup/skills/`; optionally rename to `ls-*`; add `metadata.version` if missing; register per PLATFORM_REGISTRY. |
| **Framework -> External** | Copy `_localsetup/skills/<name>/` from source, or copy the managed installed skill from `~/.local/share/agents/skills/localsetup`; use as-is in any Agent Skills host; optionally rename dir and `name` to match host conventions. |
| **Workflow package -> External** | Copy `_localsetup/workflows/<name>/`; use `SKILL.md` as the portable execution surface and treat `workflow.yaml` as Localsetup metadata. |

Skills that follow the Agent Skills spec are interchangeable; this framework adds placement, registration, and optional `metadata.version` for versioning, without breaking spec compliance. Workflow packages keep that executable shape while adding Localsetup-specific orchestration metadata.

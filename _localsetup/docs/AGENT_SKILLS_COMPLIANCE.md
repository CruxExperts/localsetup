---
status: ACTIVE
version: 3.0
---

# Agent Skills compliance (Localsetup v3)

**Purpose:** Confirm framework skills conform to the [Agent Skills](https://agentskills.io/specification) specification and document versioning and validation.

## Specification reference

- **Specification:** [agentskills.io/specification](https://agentskills.io/specification)
- **Repo:** [github.com/agentskills/agentskills](https://github.com/agentskills/agentskills)
- **Validation (optional):** Install [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref) and use its current CLI entrypoint to validate: `agentskills validate path/to/skill`

## Compliance summary

| Requirement | Framework behavior |
|-------------|--------------------|
| **Directory structure** | Each skill is a directory with `SKILL.md`; optional `scripts/`, `references/`, `assets/` per spec. |
| **name** (required) | Present in every skill; lowercase, hyphens, 1-64 chars; matches parent directory (e.g. `ls-context`). |
| **description** (required) | Present; what the skill does and when to use it; under 1024 chars. |
| **metadata.version** (optional) | Used for skill document versioning; bumped automatically when the skill file is updated (see below). |
| **allowed-tools** (optional, experimental) | Permitted when a skill needs to declare pre-approved tool hints; support varies by host, so local checks treat it as reviewable rather than invalid. |
| **Body** | Markdown instructions after frontmatter; progressive disclosure; keep under ~500 lines per spec. |
| **File references** | Relative paths from skill root; one level deep where possible. |

## Skill document versioning

- Each framework skill includes **metadata.version** (e.g. `"1.0"`) in SKILL.md frontmatter per the spec's optional `metadata` field.
- Skill version bumps are tracked separately from the framework release version. Patch is incremented (e.g. 1.0 -> 1.1) for non-breaking updates.

## Validation

- Optionally run `agentskills validate ./_localsetup/skills/ls-<name>` (after installing [skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref)) to check frontmatter and naming.
- Framework skill names use the `ls-*` prefix and match the directory name; descriptions include trigger terms for discovery.

## Interoperability

- **Framework skills are valid Agent Skills.** They use only spec-defined fields and layout; they can be copied into any Agent Skills-compatible host (e.g. [Anthropic's skills](https://github.com/anthropics/skills), Claude Code) and used as-is.
- **External spec-compliant skills can be used in this framework.** Copy the skill directory into `_localsetup/skills/`, add `metadata.version` if missing, register per [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md), and deploy. No body or structure changes required for spec compliance.
- Full import/export steps: [SKILL_INTEROPERABILITY.md](SKILL_INTEROPERABILITY.md).

## Reference

- [SKILL_INTEROPERABILITY.md](SKILL_INTEROPERABILITY.md)  - Import external skills; use our skills in other hosts; spec alignment for interchange.
- [SKILLS_AND_RULES.md](SKILLS_AND_RULES.md)  - How skills are loaded and platform paths.
- [PLATFORM_REGISTRY.md](PLATFORM_REGISTRY.md)  - Supported platforms and registration file list.
- Repo VERSION and conventional commits: [VERSIONING.md](VERSIONING.md). Skill versioning is per-skill (metadata.version), not the repo VERSION.

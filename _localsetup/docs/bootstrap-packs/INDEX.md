---
status: ACTIVE
version: 3.7
---

# Bootstrap Packs

Bootstrap packs are small, versioned bundles of Localsetup skills, workflow packages, prompts, and metadata for standing up or auditing agent operating modes.

The initial bootstrap pack targets OpenAI Codex CLI first. Other agent frameworks can reuse the same pattern later by adding platform-specific prompts and metadata without changing the core pack model.

## Pack Index

| ID | Primary platform | Localsetup pack | Status | Metadata | Prompt |
|---|---|---|---|---|---|
| `codex-agent-team` | `codex` | `bootstrap` | audit-ready | [metadata.yaml](codex-agent-team/metadata.yaml) | [AUDIT_PROMPT.md](codex-agent-team/AUDIT_PROMPT.md) |

## Source Of Truth

- Pack membership: [`_localsetup/config/pack.yaml`](../../config/pack.yaml)
- Generated pack map: [`_generated/skill-packs.md`](../_generated/skill-packs.md)
- Codex platform context: [`_localsetup/templates/codex/AGENTS.md`](../../templates/codex/AGENTS.md)

## Safety Rule

Bootstrap packs may describe global config, external runtime mirrors, and legacy replacement paths, but repo-local audit passes must not modify those locations without explicit user approval.

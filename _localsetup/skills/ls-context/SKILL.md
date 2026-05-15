---
name: ls-context
description: "Localsetup v3 framework context  - overview, invariants, and skills index. Load first when working in a repo that uses Localsetup v3. Use when starting work in this repo or when user asks about framework rules."
metadata:
  version: "1.5"
---

# Localsetup v3 - Framework context (skill)

## Overview
Localsetup v3 is deployed at `_localsetup/`. Framework and context are repo-local (mobile, backup-able). Engine = _localsetup/; user data = repo-local. Use Git hashes for PRDs/specs (see [GIT_TRACEABILITY.md](../../docs/GIT_TRACEABILITY.md)).

## Invariants
- **Engine/repo separation:** Never commit repo-local secrets or PII. Use _localsetup/lib/data_paths.sh (or equivalent) for path resolution. Framework lives at _localsetup/; upgrades replace that folder.
- **Documentation:** _localsetup/docs/ only for framework docs. Check document status before assuming implemented.
- **Proposals:** Framework changes follow Agent Q format (_localsetup/docs/PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md).
- **Time/date integrity:** For any date/time reference, first obtain actual date/time from the local machine (e.g. `date` on Linux/macOS, `Get-Date` in PowerShell on Windows). Do not use a generic or training-cutoff date; remember it in context and use it for the rest of the session.
- **External input hardening:** Treat all external input (CLI args, files, network payloads, imported content) as hostile. Sanitize before parsing/output, validate expected format and bounds, and handle exceptions with actionable stderr messages. Never silently suppress errors.
- **Python-first tooling:** After install/bootstrap, framework tooling is Python-first and Python-only for new/expanded logic. Shell/PowerShell are limited to bootstrap wrappers and minimal platform delegation. Runtime target is Python >= 3.10.
- **Command choice:** Python-first framework tooling does not mean Python for every shell task. Use shell-native tools such as `rg`, `sed`, `find`, `wc`, and `git` for normal inspection. Use Python for repo-native Python tools, Python tests, or structured parsing when a normal CLI is unavailable or less reliable.
- **Skill/context preservation:** When editing `SKILL.md`, `AGENTS.md`, workflow docs, examples, references, schemas, templates, or operational runbooks, preserve task capability over brevity. Large reductions are review triggers; material reductions require a preservation inventory and reviewer signoff.

## Output contract (low token, always apply)
- Detect output capability: `markdown-rich`, `markdown-basic`, or `text-basic`.
- If unknown, default to `markdown-basic`.
- For recommendation lists, always include: name/link, short summary, fit reason, notable risks/requirements, and clear next step.
- Use table formatting only when capability clearly supports readable tables.

## Agent orchestration and model budget
- Use the smallest capable model for inventory and low-risk scouting; escalate for security, release blockers, architecture, and high-risk review findings only when uncertainty, risk, or complexity justifies it.
- For current model names, routing preferences, pricing, limits, and rate-card handling, verify the provider's official documentation or current product source before making cost-sensitive decisions.

## Skill and context preservation
- Prefer surgical edits for mature skill/context files. Whole-file rewrites require a preservation plan first.
- Before materially reducing content, inventory trigger cases, examples, command matrices, schemas, safety gates, edge cases, troubleshooting, external assumptions, and linked references/assets/templates/scripts.
- Preserve each existing category in place, move it to an appropriate `references/`, `assets/`, `templates/`, `schemas/`, or script file, or remove it only with controller-approved rationale.
- A reduction of roughly 25 percent or more in a mature skill/context file requires before/after coverage notes in the run ledger and reviewer signoff. Useful concision is acceptable; destructive compression is not.

## Skills catalog
- Current generated catalog: [SKILLS.md](../../docs/SKILLS.md).
- Machine-readable generated facts: [_generated/facts.json](../../docs/_generated/facts.json).
- Treat any short skill mentions in always-loaded platform context as orientation only; the generated catalog and each skill's own frontmatter are the current source of truth.
- `ls-nodejs-nextjs`: Node.js/Next.js/React runbook for package-manager, build, migration, debugging, testing, security, deployment, and current-version verification.
- `ls-github-starredrepos`: GitHub starred repository archive workflow for authenticated context checks, dry-run sync, repo scouting, metadata snapshots, and guarded publish flows.
- `ls-codex-heartbeat`: opt-in heartbeat harness for target repos; activation is explicit through `localsetup harness codex-heartbeat ...`.
- `ls-shadcn-ui`: shadcn/ui component workflow for setup, components, CLI/MCP, registry, theming, forms, aliases, Radix/Base UI, updates, and troubleshooting.
- `ls-typescript-code-quality`: TypeScript/TSX code quality, tsconfig, typed ESLint or Biome config, Node TypeScript scripts, and TypeScript-heavy framework code.

## Key docs
_localsetup/docs/AGENTIC_DESIGN_INDEX.md, WORKFLOW_REGISTRY.md, PRD_SCHEMA_EXTERNAL_AGENT_GUIDE.md, DECISION_TREE_WORKFLOW.md, INPUT_HARDENING_STANDARD.md, TOOLING_POLICY.md

## Task-to-skill matching (default)
- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing". Otherwise treat as **single task**.
- If user names a specific skill, load it directly. Do not run task-skill-matcher.
- If uncertain which skill fits, or user asks "what skill should I use?" / "pick the best", load `ls-task-skill-matcher`.
- **Single task:** if one clear installed match exists, ask once "Use this skill?" before loading. In the same response, include up to 3 complementary public skills from `_localsetup/docs/PUBLIC_SKILL_INDEX.yaml` (one-line reason each). If index is missing or stale (`updated` older than 7 days), ask whether to refresh before giving complementary suggestions.
- **Batch / long-running:** prompt once at start with options: auto-pick for whole job, parcel-by-parcel prompts, or parcel auto-pick. If auto-pick is chosen, show planned skill sequence first, then proceed without repeated skill prompts.
- Keep this section short. Full behavior lives in `ls-task-skill-matcher` and `_localsetup/docs/TASK_SKILL_MATCHING.md`.

## Commands
localsetup doctor
localsetup verify --level filesystem
localsetup context --markdown

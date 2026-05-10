---
name: ls-task-skill-matcher
description: "Match user tasks to installed Localsetup skills, recommend top matches, and run single-task or batch skill-selection flow with minimal interruption. Delegates complementary public-skill discovery to ls-skill-discovery."
metadata:
  version: "1.1"
---

# Task-to-skill matcher

**Purpose:** Provide one consistent flow for choosing the best installed skill for a user task. Use this when the user asks "what skill should I use?", asks to "pick the best", or when skill choice is unclear.

## When to use this skill

- User asks for skill recommendation or best-skill selection.
- Task-to-skill match is uncertain.
- User asks to auto-pick skills for a multi-step or batch run.

## Do not use this skill

- If user names a specific skill to run, load that skill directly and skip this matcher.

## Sources and scope

- Read installed-skill candidates from the **current platform's context loader/index**. Use the platform registry documentation when available.
- Cursor: the workspace Cursor context index or skills section.
- Claude Code: the workspace Claude context file.
- Codex: the workspace `AGENTS.md`.
- Other platforms: the workspace context source identified by the platform registry.
- For complementary public-skill suggestions, load `ls-skill-discovery` and follow its public-index check, refresh prompt, and recommendation flow.

## Mode detection

- Treat as **batch** when user request includes multiple distinct subtasks, or says "batch", "multiple steps", or "run the whole thing".
- Otherwise treat as **single task**.

## Workflow

1. **Collect intent**
   - Extract user intent and any task constraints.
   - If user already named a skill, stop matching and load that skill.

2. **Rank installed skills**
   - Compare intent against each installed skill's "when to use" text.
   - Rank by relevance (keyword and description relevance).
   - If uncertain, prepare top 3 candidates with one-line "why it fits".

3. **Single-task flow**
   - If one clear installed match exists, ask once: **"Use this skill?"**
   - Same turn: include up to 3 complementary public skills from `ls-skill-discovery` when its index is ready.
   - If the public index is missing, has no `updated` value, or is stale, still show the installed match and **"Use this skill?"** first. Then load `ls-skill-discovery` and follow its required prompt behavior, including the last refresh date, computed age reminder, 7-day stale threshold, and full refresh-and-scrub sequence before returning public suggestions.

4. **Batch / long-running flow**
   - Prompt once at start with options:
     - Auto-pick best skill for the whole run.
     - Parcel-by-parcel prompts.
     - Parcel auto-pick.
   - If auto-pick is chosen, show planned skill sequence first (best-effort), then proceed without repeated skill prompts.
   - If user chooses parcels and phases are unclear, propose one parcel (whole task), then ask prompt-vs-auto-pick for that parcel.

5. **No installed fit**
   - State that no installed skill is a good fit.
   - Offer up to 3 complementary public skills to import by delegating discovery to `ls-skill-discovery`.
   - Optionally suggest creating a new skill with `ls-skill-creator`.

## Public index rules

- Do not implement a separate stale-index policy in this matcher. `ls-skill-discovery` owns the public index, the standard last-refresh reminder, stale detection, user prompt, refresh, and scrub behavior.
- When invoking `ls-skill-discovery`, preserve its required status line: `Last index refresh: YYYY-MM-DD (X days/weeks/years ago).` If the index is missing or never refreshed, use its "not built yet" prompt. If the index is at least 7 days old, include its stale refresh prompt before relying on public recommendations.
- For complementary suggestions: return up to 3 public skills from the discovery result, each with one-line fit reason.
- To import suggestions, point user to `ls-skill-importer` (or run it if user asks).

## Output style

- Keep outputs short, actionable, and consistently structured.
- For uncertain match: show top 3 installed candidates, each with one-line reason, then ask user to choose or say "pick the best".
- For single clear match: ask once, then show complementary public options in the same response.
- For public complementary suggestions, use available enriched fields from the public index entries returned by `ls-skill-discovery`:
  - Prefer `summary_short` over raw description.
  - Include notable `requirements` or `risk_flags` in one short line.
- Rendering fallback:
  - Rich/basic markdown: numbered list with labeled fields.
  - Plain text/ascii: numbered list with `Skill:`, `Why:`, `Risks:`.

## References

- [TASK_SKILL_MATCHING.md](../../docs/TASK_SKILL_MATCHING.md) - Framework task-skill matching guidance.
- [SKILLS_AND_RULES.md](../../docs/SKILLS_AND_RULES.md) - Framework skills and rules documentation.
- [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md) - Framework platform registry documentation.
- [SKILL_DISCOVERY.md](../../docs/SKILL_DISCOVERY.md) - Public skill index and discovery workflow managed by `ls-skill-discovery`.
- [ls-skill-discovery](../ls-skill-discovery/SKILL.md) - Complementary public-skill recommendations.
- [ls-skill-importer](../ls-skill-importer/SKILL.md) - Import selected public or local skills.
- [ls-skill-creator](../ls-skill-creator/SKILL.md) - Create a new skill when no installed or public skill fits.

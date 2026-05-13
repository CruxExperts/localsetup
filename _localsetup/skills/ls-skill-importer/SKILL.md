---
name: ls-skill-importer
description: Import external skills from a URL (GitHub or other) or local path; discover, validate, security-screen, and summarize each skill so the user can choose which to import. Use when the user wants to add skills from a repo/URL or local folder, or when screening and selecting skills to add to the framework.
metadata:
  version: "1.4"
---

# Skill importer

**Purpose:** Let the user point at a **URL** or **local path** containing skills; discover and validate them; run heuristic security and content-safety screening without executing candidate code; summarize each candidate; then let the user choose what to import.

## When to use this skill

- User wants to "import skills from this URL" or "add skills from GitHub/anthropics/skills."
- User has a local folder or markdown and wants to screen/import skills.
- User asks to "parse a repo and add the skills" or "validate and import skills."

## Workflow (agent steps)

1. **Get source**  - For a repository or archive URL, fetch it into a temporary directory. For a local path, use that path as the scan root. For pasted content or a single-document URL, follow [SKILL_IMPORTING.md](../../docs/SKILL_IMPORTING.md#adding-a-skill-from-paste-or-url) before writing anything to `_localsetup/skills/`.
2. **Scan**  - Run `_localsetup/tools/skill_importer_scan <path>` from the repo root. The current importer scanner takes a directory path only and writes a human-readable summary to stdout.
3. **Summarize and choose**  - Present each candidate's purpose, included files, code types, heuristic security result, and any content-safety review instructions emitted by validation tooling. Do not execute candidate code. Ask which candidates to import.
4. **Check duplicates and overlap**  - Compare selected candidates with `_localsetup/skills/` by directory name, frontmatter `name`, description, purpose, and triggers. On collision or high overlap, offer **Ignore new**, **Replace existing**, **Merge**, or **Create as new**; get explicit user choice.
5. **Normalize before copy**  - After the user chooses to proceed past security and content-safety review, run mandatory normalization using [SKILL_NORMALIZATION.md](../../docs/SKILL_NORMALIZATION.md) as the source of truth. Present the summary and key edits, get approval, and import the normalized result.
6. **Import and confirm**  - Copy the normalized skill to `_localsetup/skills/<name>/`, align frontmatter `name` with the directory, add `metadata.version: "1.0"` if missing, register per [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md), and report what changed.

## Security and content safety screening (heuristic only)

- Tool does **not** execute any skill code. It only scans file contents.
- **Security:** Flags risky execution patterns in scripts/assets, including dynamic evaluation, remote installer pipelines, PowerShell expression execution, sensitive file access, and privilege escalation markers. Results are advisory; do not block import automatically.
- **Content safety:** Use [SKILL_VALIDATION_PATTERNS.md](../../docs/SKILL_VALIDATION_PATTERNS.md) for the pattern file and review flow. For pattern hits, show references only: file, line, column, pattern id, and the pattern description. Do not display the matched candidate content.

## Sources

- **URL**  - GitHub repo, archive link, or any fetchable URL. Agent fetches; then runs scan on the resulting path.
- **Local path**  - Directory on disk with skill subdirs.
- **Single markdown**  - Use the skill-creator workflow to create a new skill from a doc; that skill is then framework-compatible and can be used with this importer flow for batch consistency.
- **Pasted content or URL to a single document**  - Follow [SKILL_IMPORTING.md](../../docs/SKILL_IMPORTING.md#adding-a-skill-from-paste-or-url). Validation is always path-based; never pass skill content through the shell.

## Compatibility

- Only directories that contain a valid SKILL.md (Agent Skills spec: `name`, `description`) are considered skills. Imported skills remain spec-compliant and interchangeable (see [SKILL_INTEROPERABILITY.md](../../docs/SKILL_INTEROPERABILITY.md)).

## Reference

- [SKILL_IMPORTING.md](../../docs/SKILL_IMPORTING.md)  - Full workflow, duplicate/overlap checks, normalization, tool usage, security notes.
- [SKILL_NORMALIZATION.md](../../docs/SKILL_NORMALIZATION.md)  - Mandatory normalization source of truth.
- [SKILL_VALIDATION_PATTERNS.md](../../docs/SKILL_VALIDATION_PATTERNS.md)  - Pattern file location, refresh behavior, content-safety review flow.
- [SKILL_DISCOVERY.md](../../docs/SKILL_DISCOVERY.md)  - Public registry discovery when importing.
- [PLATFORM_REGISTRY.md](../../docs/PLATFORM_REGISTRY.md)  - Registration file list after import.
- [SKILL_INTEROPERABILITY.md](../../docs/SKILL_INTEROPERABILITY.md)  - Import/export and spec alignment.

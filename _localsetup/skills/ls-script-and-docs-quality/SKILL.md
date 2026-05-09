---
name: ls-script-and-docs-quality
description: "Markdown/encoding standards, script generation quality, file creation discipline, documentation discipline. Use when generating scripts, creating/editing markdown or docs."
metadata:
  version: "1.2"
---

# Script and docs quality

## Markdown compatibility

- **Encoding:** Use UTF-8. Durable repo docs, scripts, manifests, and examples should be ASCII-first unless the existing file or target format clearly needs Unicode.
- **Generated/user-facing markdown:** Follow the platform default: use GFM-compatible markdown, humanized prose, links for in-repo references, fenced code blocks, and common glyphs/icons when they improve scanability. Do not remove useful glyphs solely because they are Unicode.
- **Durable framework docs:** Avoid decorative emoji, box-drawing art, and glyphs that carry critical meaning without plain-text labels. Prefer `[OK]`, `[FAIL]`, `[WARNING]`, `[YES]`, `[NO]`, `->`, `*`, and `-` when output must be portable across terminals, logs, or plain-text consumers.
- **Punctuation:** Prefer ASCII punctuation in repo docs and scripts. Avoid em dashes in durable framework text unless matching quoted/source material or an existing file convention.
- **Preview:** Verify rich markdown in GitHub or an editor preview before committing.

## Script generation quality

- **Framework tooling default:** New Localsetup framework tooling and substantial refactors must be Python 3.10+ after installation. Shell and PowerShell are limited to install bootstrap, platform entrypoints, host-compatible wrappers, or delegation to Python tooling.
- **Python style:** Use `pathlib` where practical, small helper functions, type hints for public functions and boundaries, context managers, and concise docstrings for non-obvious behavior.
- **Approved libraries:** Use the repo tooling policy for YAML, HTTP, frontmatter, and crypto dependencies. Do not hand-roll parsers or HTTP clients when an approved dependency covers the need.
- **Comments:** Explain purpose, usage, parameters, and complex decisions. Avoid comments that restate obvious code.
- **Error handling:** Validate inputs and prerequisites, catch expected exceptions with actionable messages, and never fail silently.
- **STDOUT/STDERR:** Keep normal output pipeable on STDOUT and diagnostics/errors on STDERR. Return non-zero when the task cannot continue.
- **Wrappers:** If shell or PowerShell is unavoidable, keep it thin, non-interactive, and delegating. Bash wrappers should use `set -euo pipefail`; PowerShell wrappers should use clear parameters and explicit error handling.

## External input hardening

- Treat every external input as hostile: CLI arguments, filesystem content, network payloads, copied text, imported archives.
- Sanitize untrusted strings before parsing and before printing: strip control characters, normalize whitespace, enforce max length.
- Validate type, schema, and allowed ranges before use; reject invalid values with clear error text.
- Exception handling must be explicit and actionable: print source, exception type, and message to STDERR; return non-zero exit when task cannot continue.
- Never swallow errors (`except: pass`, silent `|| true` on critical operations). Partial-failure mode is allowed only when warnings are emitted and processing decisions are explicit.

## File creation discipline

- Before creating any file: verify it belongs; minimal approach; "Is this essential?" Consolidate rather than duplicate.

## Documentation discipline

- **_localsetup/docs/ is ONLY for framework documentation.** Not for IDE setup or external tool guides. All docs must have status (ACTIVE/PROPOSAL/DRAFT/DEPRECATED/ARCHIVED). Check status before assuming a feature is implemented. See [DOCUMENT_LIFECYCLE_MANAGEMENT.md](../../docs/DOCUMENT_LIFECYCLE_MANAGEMENT.md).
- **Platform default for any generated docs/output:** Use rich markdown (code blocks, lists, typography, links for in-repo refs, glyphs where they help), humanized prose. See [OUTPUT_AND_DOC_GENERATION.md](../../docs/OUTPUT_AND_DOC_GENERATION.md).

---
name: ls-agentlens
description: Navigate and understand codebases using agentlens hierarchical documentation. Use when exploring new projects, finding modules, locating symbols in large files, finding TODOs/warnings, or understanding code structure.
metadata:
  version: "1.0"
compatibility: "Requires an existing .agentlens/ tree in the target repo. Localsetup does not ship an AgentLens generator or agentlens command."
---

# AgentLens - Codebase Navigation

## Before Working on Any Codebase
Always start by reading `.agentlens/INDEX.md` for the project map. If the target repo has no `.agentlens/` directory, this skill is advisory only; fall back to normal repository discovery.

## Generation Requirement

This skill consumes AgentLens documentation but does not generate it. Localsetup does not include an `agentlens` CLI, script, or wrapper for regenerating `.agentlens/` output.

- If the target repo already documents an AgentLens generation command, run that project-provided command from the target repo root.
- If an external `agentlens` command is installed in the environment, use the command and flags documented by that external tool.
- If no generator is available, treat `.agentlens/` as read-only navigation context and verify stale-looking claims against source files.

Do not assume `agentlens` is available from this repository or from `PATH`.

## Navigation Hierarchy

| Level | File | Purpose |
|-------|------|---------|
| L0 | `INDEX.md` | Project overview, all modules listed |
| L0 | `AGENT.md` | Optional generated agent instructions for this repo |
| L1 | `modules/{slug}/MODULE.md` | Module details, file list |
| L1 | `modules/{slug}/outline.md` | Symbols in large files |
| L1 | `modules/{slug}/notes.md` | TODOs, warnings, business rules |
| L1 | `modules/{slug}/imports.md` | File dependencies |
| L2 | `files/{slug}.md` | Deep docs for complex files |

## Navigation Flow

```
INDEX.md -> Find module -> MODULE.md -> outline.md/notes.md -> Source file
```

## When To Read What

| You Need | Read This |
|----------|-----------|
| Project overview | `.agentlens/INDEX.md` |
| Find a module | INDEX.md, search module name |
| Understand a module | `modules/{slug}/MODULE.md` |
| Find function/class in large file | `modules/{slug}/outline.md` |
| Find TODOs, warnings, rules | `modules/{slug}/notes.md` |
| Understand file dependencies | `modules/{slug}/imports.md` |

## Best Practices

1. **Don't read source files directly** for large codebases - use outline.md first
2. **Check notes.md before modifying** code to see warnings and TODOs
3. **Use outline.md to locate symbols**, then read only the needed source sections
4. **Verify stale docs against source** before relying on them; regenerate only when the target repo or external AgentLens installation provides a documented command

## Sidecars and Provenance

An optional `_meta.json` sidecar may appear beside imported skill content in some framework workflows. For `ls-agentlens`, that file is provenance only: it is not read by this skill, not required for activation, and not a substitute for the frontmatter above. If present, preserve it during source review unless a packaging or release audit explicitly classifies it as generated/private state.

For detailed navigation patterns, see [references/navigation.md](references/navigation.md)
For structure explanation, see [references/structure.md](references/structure.md)

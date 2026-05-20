# AgentLens Output Structure

## Directory Layout

```
.agentlens/
├── INDEX.md              # L0: Global routing table
├── AGENT.md              # Optional generated agent instructions for this repo
├── modules/
│   └── {module-slug}/
│       ├── MODULE.md     # L1: Module overview
│       ├── outline.md    # L1: Symbol maps for large files
│       ├── notes.md      # L1: TODOs, warnings, rules
│       └── imports.md    # L1: File dependencies
└── files/
    └── {file-slug}.md    # L2: Deep docs for complex files
```

## Lifecycle

The `.agentlens/` tree is target-repo documentation produced outside this skill. Localsetup does not ship or install an AgentLens generator.

Use the tree as follows:

1. Read `.agentlens/INDEX.md` first.
2. Read `.agentlens/AGENT.md` when it exists; treat it as generated repo-local operating guidance.
3. Navigate into `modules/` and `files/` for focused context.
4. When content appears stale, verify against source. Regenerate only with a command documented by the target repo or by an external AgentLens installation.

If `.agentlens/AGENT.md` is absent, continue with `INDEX.md`; the file is optional and its absence is not a Localsetup install failure.

## File Purposes

### INDEX.md (Always Read First)
- Project name and description
- Complete list of modules with descriptions
- Entry points (main files)
- Hub files (heavily imported)
- High-priority warnings summary

### AGENT.md (Optional)
- Generated operating guidance for agents working in the target repo
- May summarize repo conventions, caution areas, or navigation rules
- Lifecycle is owned by the target repo's AgentLens generator, not by Localsetup
- If missing or stale, use source files and other `.agentlens/` docs as the authority

### MODULE.md
- Module purpose and responsibility
- List of all files in the module
- File descriptions and line counts
- Language breakdown

### outline.md
- Symbol maps for large files (>500 lines)
- Functions, classes, structs, enums, traits
- Line numbers for quick navigation
- Visibility (public/private)

### notes.md
- TODO comments
- FIXME and BUG markers
- WARNING and SAFETY notes
- DEPRECATED markers
- Business rules (RULE, POLICY)

### imports.md
- Which files import which
- Internal dependencies within module
- Helps understand coupling

### files/{slug}.md (L2 - Complex Files Only)
- Generated for very complex files
- Detailed symbol documentation
- More context than outline.md

## Provenance Sidecars

Some imported skills or framework workflows may include `_meta.json` files as provenance sidecars. They are not part of the `.agentlens/` output structure and are not consumed by this skill. For `ls-agentlens`, any `_meta.json` beside the skill is metadata about the imported skill source only, not runtime configuration.

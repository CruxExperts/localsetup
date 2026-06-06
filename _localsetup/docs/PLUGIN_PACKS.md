---
status: ACTIVE
version: 4.1
owner_skill: ls-docs-organization
---

# Plugin Packs

Plugin packs are a portable distribution surface for existing Localsetup packs. They do not replace adapter installs; they package selected skills and workflow packages for agent platforms that support plugin-style loading.

The first supported platform is Codex. The canonical source is `_localsetup/config/plugin-packs.yaml`; generated catalogs live in `_localsetup/docs/_generated/plugin-packs.json` and `_localsetup/docs/_generated/plugin-packs.md`.

## Commands

- `localsetup plugin list --platform codex`
- `localsetup plugin plan --platform codex --plugin-packs bootstrap core --output <dir>`
- `localsetup plugin build --platform codex --plugin-packs bootstrap core --output <dir>`
- `localsetup plugin validate --platform codex --path <plugin-or-marketplace-root>`

## Output Shape

Codex builds create a marketplace root with relative plugin paths:

```text
<output>/
|-- marketplace.json
`-- plugins/
    `-- localsetup-bootstrap/
        |-- .codex-plugin/plugin.json
        |-- README.md
        `-- skills/
            |-- ls-context/
            |-- ls-communication-and-tools/
            |-- ls-workflow-audit-framework/
            `-- ls-plugin-bootstrap-context/
```

Each generated plugin includes selected skill packages, selected workflow packages, and one generated context skill named `ls-plugin-<source-pack>-context`.

## Safety

The generator copies only packages from `_localsetup/skills/` and `_localsetup/workflows/`. It rejects absolute paths, parent traversal, private maintenance paths, missing context inputs, and package symlinks that resolve outside allowed package roots.

Rebuilding replaces generated plugin directories matching selected plugin pack IDs under `<output>/plugins/`. Keep unrelated files outside those generated plugin directories.

Non-Codex platform metadata is reserved for later work. Do not claim Claude Code, Cursor, OpenCode, Kilo, or OpenClaw plugin pack support until that platform has generator and validator coverage.

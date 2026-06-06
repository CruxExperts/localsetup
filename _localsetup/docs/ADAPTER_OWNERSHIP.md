---
status: ACTIVE
version: 4.1
owner_skill: ls-framework-compliance
---

# Adapter ownership

**Purpose:** Define the ownership boundary for agent adapter-shaped directories. This is the canonical rule for install, repair, verify, detach, rollback, conversion, and migration planning.

## Principle

Adapter-shaped directories are shared agent workflow surfaces, not exclusive Localsetup-owned surfaces.

This includes repo-local and global paths such as:

- `.codex/skills`
- `.claude/skills`
- `.cursor/skills`
- `.kilo/skills`
- `.openclaw/skills`
- `.opencode/skills`
- historical `.agents/skills`
- equivalent future adapter paths with the same package-directory shape

A repo, user profile, or other agent tool may intentionally keep custom skills, files, symlinks, generated outputs, or mixed managed and repo-owned content in those directories.

## Localsetup-Owned Content

Localsetup owns only the entries it explicitly creates and records. Localsetup may create:

- a marker file such as `.localsetup-adapter.json`
- symlink-mode entries for selected Localsetup-managed packages
- portable-mode copies for selected Localsetup-managed packages
- lock, registry, report, and journal metadata under `.localsetup/` or the managed home library

The presence of a supported adapter path, a `skills` directory, or agent-compatible package names does not make the whole directory Localsetup-owned.

## Required Behavior

Install, update, repair, conversion, detach, verify, rollback, and cleanup code must treat adapter directories as mixed by default.

Required handling:

- preserve custom adapter content in place
- mutate only Localsetup-managed entries that are recorded or otherwise proven Localsetup-owned
- report same-name collisions as decisions before mutation
- report ambiguous unmanaged content as a preservation decision, not as permission to move or delete it
- avoid moving, renaming, deleting, or normalizing repo-owned content out of an adapter path unless the repo owner explicitly chooses that migration

`adapter_content`, `adapter_collision`, custom skills, non-Localsetup symlinks, and same-directory mixed content are evidence that the path is shared. They are not evidence that Localsetup should claim or clear the directory.

## Repair Planning

Repair plans must describe the managed entries they intend to change. A plan that targets an entire adapter directory is safe only when every entry in that directory is proven Localsetup-owned or the operator explicitly approved a full-directory migration.

When ownership is unclear, the safe repair output is a migration or preservation prompt. The default migration path is to leave repo-owned adapter content where it is and repair only the Localsetup-managed entries around it.

## Documentation Rule

Framework docs should say "managed adapter entries", "selected adapter links", or "Localsetup-managed entries inside the adapter" when describing Localsetup-owned content. Avoid wording that implies `.codex/skills`, `.cursor/skills`, or any other adapter directory is exclusive to Localsetup.

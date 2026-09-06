---
status: ACTIVE
version: 4.4
owner_skill: ls-framework-compliance
---

# Adapter ownership

**Purpose:** Define the ownership boundary for agent adapter-shaped directories. This is the canonical rule for install, repair, verify, detach, rollback, conversion, and migration planning.

## Principle

Adapter-shaped directories are shared agent workflow surfaces, not exclusive LocalSetup-owned surfaces.

This includes repo-local and global paths such as:

- `.agents/skills` (current Codex/shared adapter)
- `.codex/skills` (historical Codex transition surface only)
- `.claude/skills`
- `.cursor/skills`
- `.kilo/skills`
- `.openclaw/skills`
- `.opencode/skills`
- historical `.agents/skills`
- equivalent future adapter paths with the same package-directory shape

A repo, user profile, or other agent tool may intentionally keep custom skills, files, symlinks, generated outputs, or mixed managed and repo-owned content in those directories.

An adapter path may also be a repo-local symlink to another adapter-shaped directory in the same target repo. Historical `.codex/skills` links are never adopted as a compatibility alias: LocalSetup transitions only proven managed entries to `.agents/skills`, preserves custom content, and requires review for unproven links.

## LocalSetup-Owned Content

LocalSetup owns only the entries it explicitly creates and records. LocalSetup may create:

- a marker file such as `.localsetup-adapter.json`
- symlink-mode entries for selected LocalSetup-managed packages
- portable-mode copies for selected LocalSetup-managed packages
- lock, registry, report, and journal metadata under `.localsetup/` or the managed home library

The presence of a supported adapter path, a `skills` directory, or agent-compatible package names does not make the whole directory LocalSetup-owned.

## Required Behavior

Install, update, repair, conversion, detach, verify, rollback, and cleanup code must treat adapter directories as mixed by default.

Required handling:

- preserve custom adapter content in place
- mutate only LocalSetup-managed entries that are recorded or otherwise proven LocalSetup-owned
- preserve ordinary repo-owned files, custom skill directories, and repo-local symlinks that are not selected LocalSetup package targets
- report selected same-name collisions as decisions before mutation
- report unsafe adapter nodes, dangling external symlinks, and symlinks outside managed or repo-local safe roots as decisions before mutation
- preserve repo-local adapter symlinks whose targets stay inside the target repo and contain valid custom skill packages
- avoid moving, renaming, deleting, or normalizing repo-owned content out of an adapter path unless the repo owner explicitly chooses that migration

Custom skills, benign files, repo-local symlinks, and same-directory mixed content are evidence that the path is shared. They are not evidence that LocalSetup should claim or clear the directory. `adapter_content` and `adapter_collision` decisions are reserved for cases that would overwrite selected LocalSetup package names or touch unsafe filesystem nodes.

## Repair Planning

`localsetup doctor --target-directory <repo>` without a platform selector checks
the adapters recorded in that target's lockfile, including legacy adapter-state
records. A missing recorded adapter is a blocker; run `verify` and review a repair
plan. Diagnosis does not recreate adapters or change neighboring custom content.
The global-only warning applies when no adapters are recorded or selected.

An explicit platform selector checks those planned targets. An absent path is
allowed for a fresh target, but a selected path already recorded in the lockfile
must exist. An explicitly empty platform list checks no adapters and retains the
global-only warning when a target directory was provided.

Repair plans must describe the managed entries they intend to change. A plan that targets an entire adapter directory is safe only when every entry in that directory is proven LocalSetup-owned or the operator explicitly approved a full-directory migration.

When ownership is unclear or unsafe, the safe repair output is a migration or preservation prompt. Benign repo-owned adapter content does not require a prompt; the default repair path is to leave that content where it is and refresh only the LocalSetup-managed entries around it.

## Documentation Rule

Framework docs should say "managed adapter entries", "selected adapter links", or "LocalSetup-managed entries inside the adapter" when describing LocalSetup-owned content. Avoid wording that implies `.agents/skills`, historical `.codex/skills`, `.cursor/skills`, or any other adapter directory is exclusive to LocalSetup.

## Recorded installation owners

New installation lock adapter records include `owners`, a list of objects with
`scope`, `root`, and `client`. Repository attachments record `scope: repo`, the
absolute resolved target root, and each selected client ID. A shared physical
adapter retains every logical client owner. Partial detach updates this list in
both the target lock and registry receipt while preserving remaining clients
and custom neighboring content.

The existing version-2 `platform`, `platforms`, `path`, and package fields remain
compatible. Older records without `owners` remain readable; partial detach
records the remaining repository owners from their existing client membership.
This metadata describes managed installation membership, not ownership of the
entire adapter directory or permission to modify vendor configuration/state.
The typed owner model also distinguishes `personal` roots; personal attachment
and `--skill-scope` selection are not yet exposed by this metadata change.

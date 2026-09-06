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
The typed owner model also distinguishes `personal` roots. Public
`--skill-scope` selection remains pending full lifecycle integration.

## Scope planning boundary

The internal `build_install_plan(..., skill_scope=...)` API accepts `repo`,
`personal`, or `both`. Omission retains `skill_scope` from the current target
lock, falling back to the legacy lock only when the current lock is absent.
An older lock without the field and a fresh target default to `repo`; invalid
recorded scopes fail instead of silently changing intent. Explicit scope
replaces the recorded value. Scope does not select clients: an empty client
selection creates no adapter actions in any scope.

Personal plans enumerate the selected clients' manifest `global_paths`, retain
all typed logical owners on shared paths, and use the selected adapter packages.
These discovery paths are distinct from the shared canonical package library.
Planning creates no configuration or adapters. Internal personal symlink actions
use the preservation path below; portable personal actions fail preflight. The
public `--skill-scope` option remains pending full lifecycle integration.
Repository installations persist the effective scope in the existing lock.

## Personal package retention records

The registry records explicit personal adapter owners in `personal_owners`, keyed
by a deterministic `personal:` reference derived from their typed root/client
identity. Each record contains the owner, selected package names, and adapter
paths. Package references retain that identity independently of repository target
references. Multiple clients sharing a path remain separate logical owners.

Updating an explicit personal owner replaces its package selection; a
repository-only update or repository removal preserves that personal owner.
An empty personal selection still retains an ownership record. Referenced
packages participate in the existing other-owner and pruning checks. Records may
reference only packages supplied by the installation. Registry updates use the
existing caller-held package-root lock and atomic registry save.

Personal symlink application uses these retention records. Explicit personal
detach and complete inventory, verify, and repair integration remain pending.

## Personal symlink application

Internal personal plans apply under the existing package-root lock. The writer
rejects paths outside the supplied home, symlink or non-directory ancestors,
unsafe markers, existing portable adapters, and custom entries colliding with
selected package names. Other files, skills, and neighboring vendor state remain
in place. Personal portable mode is not yet qualified.

At a shared path, the visible package set includes the current selection and
packages retained by other recorded owners. The registry records each owner's
requested selection independently. The writer journals individual managed links
and the marker before changing them. Failure recovery restores those entries;
it does not replace the whole adapter directory or remove unrelated neighbors
created during the operation. Empty directories created during a failed attempt
may remain. Successful receipts use `personal_adapter_targets`, separate from
repository `adapter_targets` and `adapter_state`.

Repository detach and rollback preserve independent personal installations and
their package references. If a removal path overlaps a recorded personal adapter,
they refuse before mutation until shared-path removal is qualified. Repository
updates targeting an existing personal adapter also refuse at preflight. A single
install also refuses repository and personal actions targeting the same path.
They do not implicitly remove personal adapters.
Explicit personal detach remains pending, as do public scope selection and
complete personal inventory, verification, and repair qualification.

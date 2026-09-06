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
`--skill-scope` selection is available on plan, install, and update.

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
Planning creates no configuration or adapters. Internal personal symlink and portable actions
use the preservation path below, also used by public scope selection.
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

Personal application uses these retention records. Explicit personal
detach and repair integration remain pending.

## Personal adapter application

Internal personal plans apply under the existing package-root lock. The writer
rejects paths outside the supplied home, symlink or non-directory ancestors,
unsafe markers and custom entries colliding with
selected package names. Other files, skills, and neighboring vendor state remain
in place. Symlink and portable modes are supported internally.

At a shared path, the visible package set includes the current selection and
packages retained by other recorded owners. The registry records each owner's
requested selection independently. The writer journals individual managed links or portable package directories
and the marker before changing them. Failure recovery restores those entries;
it does not replace the whole adapter directory or remove unrelated neighbors
created during the operation. Empty directories created during a failed attempt
may remain. Successful receipts use `personal_adapter_targets`, separate from
repository `adapter_targets` and `adapter_state`.

Repository detach and rollback preserve independent personal installations and
their package references. Repository detach preserves the retained owner union
on shared paths; repository rollback uses the transaction described below. Repository
updates on a personal adapter preserve its owners through the shared writer
below; conflicting modes still fail preflight. A single install coalesces
repository and personal actions targeting the same path when their modes and
package library agree.
They do not implicitly remove personal adapters.
Explicit personal-owner removal remains pending.
Personal repair is qualified through the recorded-owner route below.

Portable packages are copied with their provenance and internal symlinks intact.
Recovery backs up only the managed package node, so a failed copy restores its
prior contents without replacing the shared parent directory. A selected owner
can change between symlink and portable mode. At a shared path, a mode change
that conflicts with an unselected personal or repository owner fails preflight.
Personal registry records retain the mode; older personal records default to
symlink, the only mode available before this field was introduced.

## Personal inventory and filesystem verification

Inventory includes a `personal` section from current registry ownership records.
It reports logical owners, their requested packages, and the expected visible
package union at each physical path. Client filtering limits requested owners;
other owners' packages remain part of the shared-path verification expectation.
An explicit empty client list inspects no personal adapter paths.

Verification for recorded `personal` or `both` installations checks the adapter
marker, owner mode agreement, complete visible package union, managed library
packages, exact symlink targets, and portable content including symlink targets.
Missing expected owner records, unsafe recorded paths, missing links, and changed
portable contents fail verification. Personal-only checks do not invent repository
adapters or historical repository transitions. These are read-only filesystem
checks; they do not claim that an external client discovered or loaded a skill.

## Recorded personal repair API

`repair_personal(source_root, home, clients=None, apply=False)` plans repairs for
recorded personal owners. Omission considers recorded owners; an explicit empty
list performs no repair, and a named client without a personal record fails
without installing it. Plans do not write configuration, journals, or locks.

Repair reuses the recorded package selections and modes. It repairs missing
managed links and drifted portable copies from the managed library. Unsafe
paths, ambiguous/custom collisions, invalid ownership metadata, and missing
library packages produce blockers; reinstall the missing library before retrying.
The API does not change registry ownership or repository lock records.

Apply rebuilds the plan under the package-root lock, journals individual managed
nodes, and verifies the result before accepting it. Failure restores prior nodes
and reports whether recovery succeeded; unrelated neighbors remain in place.
Repair journals are stored under the managed home state directory. Standard
doctor repair routes personal-only target receipts through this API.

## Scope configuration contract

The internal `InstallConfig.skill_scope` field and install configuration schema
accept `repo`, `personal`, `both`, or `null`. Omission and `null` remain unset
through loading and serialization; the planner resolves an unset value from the
recorded target scope, with `repo` as the fresh-target default. Merging an omitted
CLI value preserves the config value; an explicit scope replaces it. Scope does
not populate `platforms` or package selectors, including an explicit empty client
list. For example, `{"skill_scope": "personal", "platforms": []}` describes no
client adapters.

Plan, install, and update merge `--skill-scope` over the config value and pass
the result to the planner. Other lifecycle commands use recorded ownership.

### Doctor routing for recorded personal targets

`localsetup doctor repair --target-directory PROJECT` reads the recorded scope.
For a personal-only receipt, omitted client selectors use that receipt's clients;
an explicit empty client list selects none. Repair retains the registry's
per-client package selections and does not infer or migrate repository adapter
paths. Report-only and migration-plan modes suppress application even when apply
was requested. Invalid repair modes or unreadable lock metadata prevent writes.
The existing `--repair-mode safe-repair --yes` application flow uses per-entry
transactional recovery and verifies personal adapter contents. Resolver issues
are reported separately; this route repairs personal adapters only.

Automatic selector-free plan/install/update uses recorded personal update
planning when adapters are healthy. If adapters need repair, the command reports
or applies that repair first; rerun update to refresh packages afterward.
Combined `both`-scope doctor repair refuses before repository pre-actions until
coordinated owner-aware repair is qualified. Combined-scope operations are not
implied by personal repair support.

### Distinct selections on a shared personal path

Internal personal actions and their lock receipts may include `owner_packages`,
a mapping from canonical personal owner keys to requested package-name lists.
Its keys must match the action's owners exactly, and the union of its lists must
equal the action's `packages`. Each owner must request the same set and mode across all of its action paths.
Validation runs before adapter writes and again when recording ownership. An empty list retains an owner with no requested
packages. Without this field, existing actions continue to assign their package
list to every selected owner.

The adapter exposes the physical union, including retained unselected owners;
the registry records each selected owner's own list and package references.
This representation supports coalesced updates without broadening selections.
The internal recorded-update planner below consumes this representation.

### Recorded personal update planner

`build_recorded_personal_plan(source, home, target)` prepares a package refresh
for a healthy personal-only installation. It selects the clients recorded in
the target receipt, reads their current registry selections, retains recorded
paths and modes, and coalesces writes with distinct `owner_packages`. It retains
the recorded global baseline and refuses packages absent from the update source.
It does not reinterpret presets or discover new client write paths. Repair
unhealthy personal adapters before planning an update.

The normal apply transaction refreshes source packages and adapters. Receipt and
registry byte hashes are checked under its package-root lock before mutations;
if ownership changes after planning, rebuild the plan. Custom adapter neighbors
remain in place. Automatic selector-free CLI routing uses this planner for
healthy recorded personal targets. Qualification covers selected clients with
shared paths in symlink and portable modes; it does not establish host application behavior.

For an existing personal target, preview with
`localsetup plan --target-directory PROJECT`, then refresh with
`localsetup update --target-directory PROJECT`. Omit client/package selectors
to retain recorded selections; `auto_mode: recorded_personal` identifies this
route in JSON output. Preview does not change the receipt or registry. A
`repair_required` result handles adapter drift before package refresh. These commands retain an existing scope.

## Public scope selection

Preview and apply a personal installation:

```bash
localsetup plan --target-directory PROJECT --tools cursor --skill-scope personal --skills ls-context
localsetup install --target-directory PROJECT --tools cursor --skill-scope personal --skills ls-context --apply
```

Use `repo` for repository adapters or `both` for both sets of paths. These scope
choices do not change the canonical shared package library.

On a fresh target, scope alone selects no clients, even when existing adapter
directories could otherwise trigger automatic discovery. Omission retains the
recorded scope; repeating that scope with no selectors keeps automatic recorded
updates. To change personal package selections, name clients explicitly.
Changing a recorded scope currently fails before installation: coordinated
ownership migration is not yet qualified. Same-plan repository/personal actions on one path
require matching modes and package libraries.

## Repository updates on personal adapter paths

A repository update may target a directory already exposed by personal owners.
When modes agree, the writer combines the new repository selection with retained
personal selections and other repository owners, excluding the updating
repository's old selection. The original repository receipt records only its
requested packages; personal owner records remain unchanged. Legacy repository
receipts retain their existing client-membership interpretation.

These shared writes use the home-bound path checks and per-entry journal used
by personal adapters. A failed write restores managed entries while preserving
custom neighbors, including files created during the failed operation. Mode
changes that conflict with a personal owner fail before mutation. Shared-path rollback follows the transaction below.

Repository filesystem verification checks the full recorded owner union on a
shared path and reports the repository request separately from that union.

## Coalescing both scopes in one plan

When a `both` plan contains repository and personal actions for the same path,
preflight pairs them only if their modes and package-library paths agree.
Duplicate actions within one scope are rejected. Apply writes the directory
once through the personal entry journal, using the union of both requested
sets and retained owners. It excludes the updating repository's old selection.

The repository and personal actions remain separate in the plan and receipts;
coalescing physical writes does not merge their logical ownership or selections.
Filesystem verification checks the visible union. Conflicting modes or library
paths fail before writes, and the home-bound path and custom-content protections
remain effective.

## Detaching repository owners from shared paths

Repository detach removes only repository exposure on a path retained by personal
owners. It rewrites the managed union with an empty repository request, preserving
personal and other repository owners. Shared directories use per-entry journal
backups, including receipt backups, rather than whole-parent restoration. If a
receipt write fails, recovery restores prior managed nodes and receipts while
keeping custom neighbors, including files created during the failed operation.

A `both` receipt retains its personal targets and clients. Removing its last
repository target changes its recorded scope to `personal`; personal owner
records and package references remain intact. Detach preserves the canonical
package library. Explicit personal-owner removal remains separate lifecycle work.

Backup cleanup runs after transaction commit. A cleanup failure returns a warning
and the committed journal path; it does not restore obsolete ownership receipts
or attempt rollback using partially deleted backups.

## Rollback serialization and path preflight

Rollback holds the same package-root lock as installation and detach. Before
removing any package or adapter, it validates every recorded package and adapter
path. A malformed later entry therefore cannot cause partial deletion of earlier
valid entries. Recorded package paths must resolve to direct children of the
managed library; the library root itself is never a package removal target.
Adapter parents must resolve beneath the attachment target. Lock contention
follows the existing package-root timeout contract.

## Rolling back a repository with shared personal paths

When recorded repository adapters overlap personal owners, rollback preflights
retained unions and package pruning, then journals adapter entries, package
nodes, registry, and current/legacy repository receipts as one transaction.
Shared adapters retain personal and other repository selections. Packages with
remaining references stay installed. The repository registry target and receipts
are removed; independent personal ownership remains recorded and verifiable.

A failure restores managed entries and receipts without replacing adapter parent
directories, preserving custom neighbors created during the attempt. Empty
adapter directories may remain. Recovery errors are recorded in the journal.
Backup cleanup follows commit; cleanup failure reports a warning and journal
path without reverting committed ownership. This transaction applies to rollback
with personal overlap; the nonshared rollback path retains its existing behavior.
Explicit personal-owner removal is not implied by repository rollback.

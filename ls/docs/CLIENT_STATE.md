---
status: ACTIVE
version: 4.2
owner_skill: ls-framework-compliance
---

# Deterministic Client State

LocalSetup gives each registered client variant one private runtime-state root. The root comes only from `ls/config/clients.yaml`; callers do not invent directories or search historical locations.

## Scope selection

`localsetup state path --client <family>/<variant>` probes the current directory with Git. Inside a normal worktree—including a linked worktree or submodule—it selects the variant's repo state root. Outside a repository it selects the verified global root. A present but broken `.git` marker, bare repository, ambiguous Git failure, unknown client, or unsupported root fails explicitly. Path escape and existing symlink or non-directory path components fail with `unsafe_state_path`. This check runs before the CLI reports a state path or mutates state. Every existing global component from its configured owner through the state root must be a current-user-owned directory without group or other write permission. An existing owner's immediate parent is bound by the pre-owner rule; unrelated higher ancestors are not. When the owner is absent, its nearest existing ancestor—and any intermediate that appears before live traversal—must be a root- or current-user-owned directory that is either not group/other writable or has the sticky bit, preserving standard roots such as `/tmp` mode `1777`. Those exact predicates are rechecked through live descriptors before allocation or verification and before the final root is normalized to `0700`. Repo roots do not inherit the global rule.

Explicit `--scope global` does not inspect or require the caller's working directory. Automatic and repo scope continue to require a valid directory for Git detection.

Repo state is registered as one exact anchored child in Git's resolved `info/exclude`, unless Git confirms that an existing rule already covers it. LocalSetup never infers coverage from similar text and never ignores the whole client directory, its policy, or its skills. A plan privately binds the repository root, exclude parent, and the exact present-or-absent exclude entry by filesystem identity while keeping the public payload unchanged. Apply opens those directories without creating them, rechecks every bound path and the held lock/exclude descriptors around probes and writes, and creates a planned-absent exclude only with exclusive creation. Every plan and successful apply receipt uses a final strictly decoded UTF-8 read from the still-bound exclude descriptor. Existing exclude and lock files must be owned, single-link regular files without group or other write permission; modes `0600` and `0644` are accepted. Before creation or writing, failures are typed and non-mutating. Once a new exclude is exposed or any append begins, a later failure preserves the current path and bytes and returns `exclude_commit_ambiguous`; LocalSetup never truncates or unlinks recovery state. `state path` is read-only unless `--apply-exclude` is supplied; artifact allocation validates its full request before applying the exact exclude.

## Artifact contract

Allocate an artifact with:

```bash
localsetup state allocate --client codex/codex-cli \
  --agent controller --purpose release-checkpoint --extension md \
  --kind restart-artifact --schema restart-v1 --producer controller \
  --content-file checkpoint.md
```

The filename is `<agent>-<UTC-YYYYMMDDTHHMMSSmmmZ>-<purpose>.<ext>`. The timestamp must be a real UTC millisecond. A same-millisecond collision adds fixed `-01` through `-99`; existing files are never overwritten. Agent, purpose, producer, consumer, kind, schema, extension, predecessor, checkpoint, content file, and metadata schema are validated before exclude or state mutation. When the state root already exists, that preflight also opens and validates it read-only without creating or normalizing paths; allocation repeats the checks to close races. Artifact content must be bytes and at most 16 MiB through the CLI, direct keyword API, or a prepared request; the exact limit is accepted and every prepared field is canonically revalidated before mutation. The repository's metadata schema is always enforced as the immutable baseline; a caller schema may only add constraints. Predecessor and checkpoint identifiers use normalized POSIX-relative paths of at most 512 characters; Windows drives, UNC paths, backslashes, traversal, and controls are rejected. Canonical encoded sidecar metadata must fit the verifier's 1 MiB limit before allocation begins.

The state root is owner-only `0700`; artifacts, sidecars, pending receipts, and internal lock files are `0600`. Each newly created hierarchy level is opened and validated, then the child and its still-open parent are synced in that order; uncertain creation durability returns `artifact_commit_ambiguous`. Allocation waits for the crash-releasing file lock for one fixed bounded interval. A timeout returns `artifact_locked`; a successful waiter then chooses the deterministic same-millisecond suffix. A bounded pending receipt lets the next allocation recover an interrupted owned pair without deleting a foreign collision. A durability failure after filesystem commit returns an explicit ambiguous result instead of claiming success or silently duplicating work.

Each artifact has a `*.meta.json` sidecar binding its state-root-relative filename and timestamp, SHA-256 and size, format, kind/schema, producer, predecessor/checkpoint, sorted consumers, client/scope, the canonical F01 registry schema version and variant digest, and—at repo scope—the current HEAD/ref with repository root represented only as `.`. Absolute machine paths, Git diagnostics, and repository remotes are not stored or returned.

Verify before resume:

```bash
localsetup state verify --client codex/codex-cli \
  --artifact controller-20260715T160203456Z-release-checkpoint.md
```

State operations reopen directories and files through non-symlink owner handles and recheck state-root identity, registry digest, and repo/ref before use. Verification fails on filename/timestamp, schema, path, hash, size, client/scope, registry, repository/ref, file type, symlink, or containment mismatch. Verification mismatches return sorted JSON and exit `1`; invalid requests and safe operational failures return a sanitized JSON error envelope and exit `2`. A filename helps discovery; the sidecar and current verification are authoritative.

## Handoff vocabulary

- **controller ledger** — ordered private execution evidence and decisions
- **accepted checkpoint** — reviewed state safe to resume from
- **repo/ref binding** — `.` plus the exact Git HEAD and symbolic ref
- **client capability snapshot** — separately versioned facts about the active client
- **restart artifact** — complete durable handoff payload
- **resume verification** — recheck metadata, repository/ref, current diff, and acceptance evidence before acting
- **complete/blocked stop condition** — explicit terminal evidence or the exact unresolved dependency

This surface does not provide legacy migration, a state service, CAS, outbox/replay, databases, runner/session behavior, or goal-loop defaults. It does not invent or normalize native slash commands.

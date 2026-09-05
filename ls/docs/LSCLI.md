---
status: ACTIVE
version: 4.4
owner_skill: ls-architecture
---

# LSCli bootstrap and diagnostics

LSCli is the integrated CLI for LocalSetup (LS). Its command is `lscli`; the
existing framework command and Python distribution remain `localsetup`.
The current bootstrap provides help, version output, and read-only diagnostics.
Agent execution is not yet available. A verified SDK payload alone does not
establish protected runtime, sandbox, provider, or supervisor readiness.

```bash
lscli --help
lscli --version
lscli doctor
lscli doctor --format json
```

Help and version return 0. Doctor currently returns 3 because execution gates
remain unavailable; payload verification is reported independently. Calling
`lscli` without a subcommand returns 3 with diagnostic guidance on standard error.
Invalid arguments return argparse's status 2. Doctor text or JSON goes to standard
output. None of these commands loads provider/SDK modules, discovers credentials,
makes provider calls, or creates configuration or state directories.

The JSON diagnostic is versioned with `schema_version: 1`. It includes `product`,
`application`, `framework_version`, `status`, `sdk_payload`,
`execution_available`, `locations`, and `issues`. Payload status is `verified`,
`missing`, or `invalid`. Verification inspects the installed private payload's
manifest and files without importing them. Source/editable development has no
installed private payload and never falls back to the canonical vendor tree.
A missing or damaged payload calls for a verified framework wheel installation.
Diagnostic integrity evidence is not artifact authentication.

## State locations

The new CLI follows the existing global framework home under the user's home:

| Purpose | Path relative to the user home |
| --- | --- |
| Durable CLI state and future sessions | `.local/share/localsetup/state/lscli` |
| Explicit provider profile configuration | `.local/share/localsetup/config/lscli/profiles.json` |
| Managed release runtimes | `.local/share/localsetup/runtimes/lscli` |

Diagnostics only reports these locations. Offline setup and runtime-use leases
are implemented as described below. Profile creation, session persistence,
sandbox protection, worker supervision, PATH collision handling, and agent
dispatch remain subsequent gates. A reported location does not enable them.
Existing framework state, adapter ownership, and stored heartbeat identifiers
are unchanged. See [SDK source and dependency maintenance](SDK_FORK.md) for the
private payload, dependency lock, build, and artifact boundaries.

## Candidate verification

A Python 3.12/Linux wheel installation was checked outside the source checkout.
Its installed `lscli` command returned help and version successfully; doctor
reported `sdk_payload: verified` and `execution_available: false` with exit 3.
The check used a nonexistent temporary user home and confirmed that no home or
state directories were created. A separate isolated Python invocation confirmed
the installed module origin and absence of SDK, provider, HTTP, and YAML imports.
This evidence qualifies the provider-free bootstrap only.

## Runtime lease foundation

The internal `runtime_use` context manager provides shared use leases and
exclusive upgrade leases over one persistent lock inode in the managed runtime
root. Shared leases coexist; an exclusive lease waits for all users. Waits use a
finite, nonnegative monotonic timeout and raise `TimeoutError` on contention.
Process exit and exceptions release the lease. The lock file is never unlinked
or replaced during normal use, preventing separate lock generations.

The runtime root must already exist, be owned by the current user, and deny
writes to other users. Descriptor-relative traversal rejects symlink components;
the lock must be a private regular file with one hard link. The implementation
requires a qualified POSIX `flock` backend. It does not create runtime directories
or change their permissions. This advisory lock coordinates cooperating callers;
the sandbox must separately prevent untrusted same-user processes from writing
the runtime or replacing its root. Do not rename the root while it is leased.

When an operation also needs the existing framework package-root lock, acquire
that lock first, then the runtime lease. Do not convert a shared lease to an
exclusive lease in place. Installation and selection now consume this foundation. Worker lifetime
supervision and platform qualification remain required before execution can be
enabled; doctor continues to report that
execution is unavailable.


## Explicit offline runtime setup

Setup can plan or apply a runtime installation from a specific verified framework
wheel and a local directory containing its audited external artifacts. It does
not select a release from the network, download Python, discover credentials, or
make provider calls. Obtain the expected SHA-256 from the trusted release source;
a hash computed from an untrusted download does not authenticate it.

```bash
lscli setup --plan --wheel /path/to/framework.whl --sha256 EXPECTED_SHA256 --wheelhouse /path/to/dependency-artifacts
lscli setup --apply --wheel /path/to/framework.whl --sha256 EXPECTED_SHA256 --wheelhouse /path/to/dependency-artifacts --timeout 300
```

Replace all placeholders. Both commands emit JSON to stdout and return 0 on
success; setup errors produce diagnostics on stderr and return 2. Keyboard
interruption returns 130 after command teardown. Plan validates
artifact identity, SDK payload, local inputs, and workspace separation without
creating persistent runtime state. The result records the effective workspace,
framework version, artifact digest, runtime root, and release path. The default
root is the managed runtime path above; `--runtime-root` selects an explicit
alternative. The runtime must lie outside the current directory and every
enclosing repository, and cannot contain that workspace. Wheel input is limited
to 256 MiB; ambiguous or oversized distribution metadata is rejected.

Apply acquires an exclusive runtime lease, creates a digest-named release slot,
and writes an incomplete installation record. It creates the environment at its
final path, avoiding virtual-environment relocation. Build and runtime dependencies
come from the wheel's hashed exports and local artifacts only. Build tools are
preloaded; build isolation is disabled so no implicit build dependencies are
resolved. The framework wheel installs without dependency resolution. Dependency
compatibility and installed SDK payload checks must pass before activation.
The managed CLI launcher invokes the absolute installed Python with `-I -B`,
preventing inherited Python path settings, the working directory, or user site
hooks from selecting checkout code at startup. This rewrites only the framework
CLI launcher; the isolated SDK worker and sandbox still require separate checks.

Only a completed installation replaces `current.json`, using an atomic regular
file replacement and filesystem flushes. The record retains the previous digest,
and prior release directories and sessions remain untouched. Installation
commands share one deadline after preflight, suppress output, and terminate their
process groups on completion or interruption. A failed command reports failure
and retains the incomplete slot for inspection; it does not replay or remove it.
If the process stops near activation, inspect `current.json` and the slot's
`status.json` before deciding what happened. Existing slots are refused, including
completed slots. Use explicit verified re-selection to recover a prior slot:

```bash
lscli setup --reselect RELEASE_SHA256 --runtime-root /path/to/runtimes
```

Re-selection holds an exclusive lease, verifies the completed record and installed
inventory, and atomically changes selection without replaying installation. It
refuses incomplete, unsealed, or altered slots and preserves the current pointer
on validation failure. Do not manually edit records to bypass validation.

Installation copies dependencies without cache hardlinks and runs build commands
with a private umask. Before activation it seals the environment's exact paths,
file hashes, modes, allowed interpreter aliases, and host interpreter bytes.
Selection verifies this inventory under the shared lease; added files, changed
content, unsafe permissions, and unexpected symlinks or hardlinks are refused.
The managed launcher disables bytecode writes to keep the inventory stable.
A host interpreter update invalidates that qualification and requires a new
verified runtime installation. This integrity check detects drift; it does not
provide artifact authentication or prevent a same-user writer from racing it.

The internal `selected` context holds a shared lease and checks the selected
completion record for the entire caller-owned operation. Runtime installation
and integrity-checked selection are implemented, but worker supervision and
sandbox protection still need integration. Successful setup
does not enable agent execution or change doctor's unavailable-execution result.
The installer assumes the caller trusts the uv executable and supplied release
digest; artifact authenticity and platform qualification remain external gates.

The Python 3.12/Linux candidate also passed offline installation outside the
checkout, inventory verification before and after managed doctor execution with
an inherited checkout `PYTHONPATH`, explicit re-selection, and rejection of a
tampered installed file while preserving the selection pointer. This qualifies
candidate integrity and recovery behavior only; it is not released-artifact or
sandbox qualification.

## Isolated SDK import qualification

Managed installation runs a separate installed Python process with `-I -B` to
qualify SDK imports before sealing or selecting the runtime. Its private
`ls.core.agent.sdk_worker --probe` module verifies the bundled manifest, refuses
preloaded SDK namespaces, and installs a manifest-backed importer for the three
upstream namespaces. It compiles verified source bytes directly, bypassing cached
bytecode. Missing SDK modules cannot fall through to an ambient installation;
loaded module origins must match the private payload. Package resources remain
available through the package loader. The supervisor/bootstrap process does not
import SDK code.

This probe makes no provider request and enables no tools. It establishes import
qualification, not sandbox isolation or agent readiness. The owning caller must
hold the runtime lease and protect the installed tree for worker lifetime;
provider transport, broker authority, and supervisor dispatch remain pending.

The Python 3.12/Linux installed candidate verified its loaded SDK origins with
inert substitute packages beside the installed distribution and an ambient SDK
path. All loaded SDK modules came from the private payload; removing the fixture
restored the exact runtime inventory. This checks namespace substitution, not
compatibility with every separately installed upstream SDK distribution.

## Explicit provider profiles and transport

The provider foundation reads a named profile from an explicit JSON file without
creating state or looking for other credentials. Schema version 1 uses this shape:

```json
{
  "schema_version": 1,
  "profiles": {
    "example": {
      "base_url": "https://provider.example/v1/",
      "api": "chat_completions",
      "model": "MODEL_ID",
      "credential_env": "LSCLI_EXAMPLE_KEY",
      "timeout_seconds": 60,
      "capabilities": ["streaming"],
      "allow_loopback_http": false
    }
  }
}
```

Replace the illustrative endpoint and model with an explicitly qualified service.
`api` is `chat_completions` or `responses`. Capabilities are an explicit subset of
`streaming`, `tools`, `images`, and `native_schema`; declarations do not establish
endpoint qualification or grant tool/disclosure authority. The named credential
variable is resolved only from the environment supplied by the owner. Credential
values are not stored in profile JSON. Missing credentials fail before transport
construction. Unknown profile fields, duplicate JSON keys, invalid capabilities,
and nonpositive/nonfinite timeouts are rejected. Configuration is limited to 1 MiB;
timeouts are limited to 3600 seconds.

HTTPS uses the locked certifi trust store. HTTP requires explicit opt-in and a
literal loopback IP. URLs cannot carry credentials, query strings, fragments,
escaped paths, or traversal segments. The client disables ambient proxy/CA
settings, implicit SDK credential and organization/project discovery, redirects,
and SDK/transport retries. The adapter clears the pinned SDK's merged custom-header
field before body serialization; dependency updates must retain the ambient-header
regressions because this uses an SDK implementation detail. The final transport permits only POST to the selected
API endpoint and rebuilds its six wire headers (Host, authorization, user agent,
content type, accept, and content length) after SDK request construction. Serialized
JSON requests are limited to 16 MiB; ambient custom headers cannot pass through. Identity is exactly `LocalSetup/<framework_version()>`; SDK
telemetry-identification headers are removed. There is no fallback endpoint.

Deterministic transport fixtures cover both APIs, final headers, a single attempt
on rate limiting, and redirect refusal. No live provider compatibility is implied.
The configured timeout is an HTTP operation timeout; supervisor wall-clock budgets,
stream/output bounds, cancellation, and task-bound disclosure grants remain
required before dispatch is enabled. The shared client is not yet connected to
public agent/completion commands or the existing QC wrapper.

## SDK model adapter

The isolated worker's model factory connects Chat Completions or Responses to
the shared client. It requires the active private importer and checks SDK origins
before model construction and after use. It passes the selected model explicitly
and replaces inferred model profiles with conservative SDK defaults plus declared
tool/schema capabilities; native provider
tools and inferred JSON-object output are disabled. These declarations remain
separate from broker grants and endpoint qualification.

Deterministic fixtures exercise both adapters through the SDK direct-request API,
verify tool-free request bodies and final identity, and deserialize successful
responses. The factory does not expose public dispatch or bypass pending request
budgets, supervisor outcomes, broker permissions, sandbox, or session recovery.

The Python 3.12/Linux installed candidate passed the same deterministic fixtures
outside the checkout, including a model name that triggers upstream inference:
system roles remain explicit and no inferred context-window claim survives.
Installed payload origins and the runtime inventory were verified afterward.

## Bounded worker supervision

The internal `probe_runtime` supervisor holds the selected runtime's shared lease
through worker teardown. It starts installed Python with `-I -B`, a minimal
environment, private umask and a new POSIX process group. Schema-1 stdin currently
accepts only `{"schema_version":1,"operation":"probe"}` followed by EOF. The worker
emits a `ready` event and one qualification `result`, each with schema version,
zero-based sequence, type and object data. Generic agent/tool dispatch is not
available through this protocol yet.

The supervisor concurrently handles pipes with bounded storage: requests up to
4096 bytes, stdout up to 1 MiB, and diagnostics up to 64 KiB. It owns the monotonic
execution deadline, polls cancellation during process supervision, closes stdin
after the request, and kills the process group on exit, timeout, cancellation or
failure. Pipe-holding descendants are terminated when their worker exits. Raw
worker diagnostics are discarded rather than included in terminal results.

Internal terminal states are `completed`, `failed`, `protocol_error`,
`output_limit`, `timed_out`, and `cancelled`. Completion requires both the exact
ready/result protocol and process exit zero; neither alone is success. A result
is not controller acceptance of any repository task. Preflight/lease errors
remain exceptions. Cancellation during lease acquisition or synchronous inventory
verification is not yet interruptible; remaining deadline is checked before
spawn. Process groups do not contain descendants that deliberately create new
sessions; sandbox containment remains a separate required gate. Steering,
approvals, durable operation recovery and agent dispatch remain pending.

The Python 3.12/Linux installed candidate completed this supervised probe outside
the checkout, with private SDK origins and unchanged runtime inventory. Focused
subprocess fixtures cover malformed/duplicate events, nonzero exit despite a valid
result, output limits, active/pre-start cancellation, deadlines and pipe-holding
children. These checks qualify the probe lifecycle only.

## Task-bound file broker

The internal file broker accepts a supervisor-owned immutable grant bound to a
task, session, absolute workspace root, monotonic expiry and revocation event.
Read, write and provider-disclosure scopes are separate canonical relative paths;
`.` covers the granted tree subject to protected-path rules. Reading for provider
use requires both read and disclosure authority. Grants must never be reconstructed
from model responses, compacted summaries or stored conversations.

Broker reads/writes use one existing private lease root shared by all cooperating
sessions, separate from the workspace. Reads take shared leases and replacements
exclusive leases. Descriptor-relative traversal refuses symlinks; regular files
must be owned by the current user, have one hard link, and lack special modes.
Operations are limited to 8 MiB. Reads reject observed concurrent file changes;
writes use exclusive temporary files, preserve existing mode/owner/group and
extended attributes, flush file data, recheck authority and target identity, then
atomically replace and flush the directory. Failed preparation leaves the original
file in place and removes the temporary file. Missing parent directories are not
created. A directory flush failure after replacement is an uncertain mutation,
which future operation-journal reconciliation must resolve before retry.

Private/control path segments `.git`, `.agents`, `.codex`, `.claude`, `.ssh`,
`.env` and `.env.*` are refused; writes to `AGENTS.md` are also refused. This
preserves governing context and mixed adapter content. These defaults do not
identify every possible secret: the supervisor must issue appropriate scope and
protected runtime/state boundaries before dispatch.

The broker is internal and not yet exposed as SDK tools. A cooperating lease and
pre-replacement identity check do not stop an untrusted same-user process from
renaming directories or racing the final replacement. Tool-enabled execution must
combine sandbox containment, shared target/session ownership, prompt-bound
approvals and durable journaling; public integration is pending. Grant expiry/revocation
is checked before and after lease waits and before returning data or replacing a
file; it does not interrupt a blocked filesystem syscall.

## Optional native sandbox artifact delivery

Offline setup accepts `--sandbox-bundle /path/to/native.zip` together with
`--sandbox-sha256 TRUSTED_SHA256` on both `--plan` and `--apply`. These inputs
cannot accompany `--reselect`. The expected outer digest must come from the
trusted artifact publisher. Setup does not discover or substitute a host
`bwrap`, download native code, or execute the bundle during planning.

The schema-1 ZIP contains exactly four regular, nonempty entries: `bwrap`,
`bubblewrap-COPYING`, `libcap-copyright`, and `manifest.json`. Compressed and
expanded content are each limited to 16 MiB; the manifest is limited to 16 KiB.
Duplicate keys, extra entries, symlink entries, mismatched hashes and unsupported
component identities are rejected. The manifest has exactly these fields:

- `schema_version`: integer `1`.
- `target`: `{"os":"linux","machine":"x86_64","libc":"glibc","minimum_libc":"2.39"}`.
- `components`: exact bubblewrap and static libcap version/input-digest records
  defined by `ls/core/agent/native_bundle.py`.
- `files`: SHA-256 values for the three payload entries, keyed by their exact names.

This delivery contract accepts bubblewrap 0.12.0 and the specified patched Ubuntu
libcap build input. It requires Linux x86_64 with glibc 2.39 or newer; those checks
are installation prerequisites, not a claim that every such host is functionally
qualified. The authenticated bundle supplies the executable's provenance;
manifest strings and an ELF header alone do not establish trustworthy code.
Native release production must retain corresponding source, licenses, build
provenance and SBOM evidence and satisfy redistribution requirements before
publication. No native release artifact is published by this setup operation.

With a bundle, the runtime slot identity is the SHA-256 of the UTF-8 string
`lscli-runtime-v1\nWHEEL_SHA256\nBUNDLE_SHA256\n` with placeholders replaced by
lowercase digests and `\n` represented by newline bytes. Plan and installation
records expose this identity as `sha256`, retain the framework digest separately
as `wheel_sha256`, and record `sandbox_sha256`. Without a bundle, existing
wheel-digest slot identities and records remain compatible. Re-selection takes
the runtime slot identity, so two native variants never overwrite one another.

Apply rechecks and holds the authenticated bytes in memory, writes the payload
under `venv/lscli-native`, and seals binary, manifest and license content and
permissions with the environment inventory before activation. Changed native
files invalidate selection and recovery just like changed Python files. The
binary is private and executable; other entries are private regular files.
A bundle-less runtime remains usable for provider-free diagnostics. Neither
bundle delivery nor its platform checks enables tool execution: argument
construction, containment qualification and broker integration remain required.

## Process sandbox invocation foundation

The internal `ProcessGrant` binds an exact immutable argument tuple to a task,
session, private staging directory and monotonic deadline, with explicit
revocation and a separate `disclose_output` flag (false by default). Commands
start with an explicit executable under `/usr/bin`; there is no shell expansion
unless the granted command itself invokes a shell. Arguments are limited to 256
entries and 16 KiB of UTF-8 bytes. A grant is supervisor-owned authority, never
constructed from saved conversation text or a model-generated request alone.

`invocation` holds the selected, verified runtime lease through the caller's
process teardown. It refuses a missing native payload; it cannot fall back to a
host executable. The invocation result includes the exact command tuple, a
protected launcher working directory, and an immutable minimal launcher
environment. The caller must use all three when starting bubblewrap; inheriting
host loader settings such as LD_PRELOAD would run code before namespace setup.
The Linux namespace layout exposes `/usr` read-only, a synthetic
`/dev`, private `/proc` and `/tmp`, and the staging directory writable at `/work`.
It clears the inherited environment and sets only PATH, HOME and LANG. All
supported namespaces are isolated, further user namespaces are disabled, Linux
capabilities are dropped, and parent death terminates the sandbox. The original
workspace, runtime tree, broker state, user home and host network are not mounted
or shared. The host system toolchain remains a trusted platform prerequisite. Runtime roots
overlapping `/usr` are rejected. The caller must ensure this exposed system tree
does not contain other protected workspace, broker state or private material;
such a host layout is not qualified by this backend.

Staging must be a dedicated, exclusively owned broker-prepared snapshot, separate
from runtime and system trees. Its root is private; contents must be owned
regular files or directories, with no symlinks, hardlinked files, special modes,
shared writes, protected context or private-state entries. Inventory is limited
to 30,000 entries and 256 MiB before invocation. These are input limits, not disk,
memory or process-count limits on a running command. A caller must not mutate or
rename staging while it is being checked or used. Do not pass the original
workspace as staging. Snapshot creation must copy only content authorized for
process access and omit policy/private material; commands can create disposable
files in their private snapshot but cannot write those files back themselves.

This foundation constructs invocations; it does not dispatch public tools.
The owning broker must still prepare snapshots from file grants, supervise total
deadlines and revocation during execution, bound output and runtime resources,
authorize provider disclosure of that output, and journal any accepted workspace
writeback through the file broker. Holding a runtime lease alone supplies none
of those authorities. Current context loading happens outside this sandbox;
`AGENTS.md` and protected private directories are not copied into tool snapshots.

## Bounded sandbox process capture

The internal process broker runs a prepared `ProcessGrant` through its complete
`Invocation` (command, protected working directory and minimal environment),
retaining the selected runtime lease until the supervisor has killed and reaped
the owning process. It sends EOF on stdin. The grant's monotonic expiry covers
lease qualification and execution; the remaining time becomes the supervisor's
execution deadline. Grant revocation and caller cancellation both stop active
work. Synchronous inventory checks and lease waits remain bounded by their
existing mechanisms and are not immediately interruptible by cancellation.

The existing supervisor pipe engine supports explicit process capture alongside
its unchanged default SDK probe protocol. Capture concurrently drains stdout and
stderr, capped at 1 MiB and 64 KiB respectively. Complete output is decoded as
UTF-8 with replacement for malformed bytes. Exit zero gives `completed`; nonzero
exit gives `failed`, retaining the return code and captured diagnostics. Timeout,
cancellation and overflow give `timed_out`, `cancelled` and `output_limit` and
omit partial output. A completed command is not evidence that its requested task
was accepted or that workspace changes were committed.

`provider=True` requires `ProcessGrant.disclose_output=True` before execution.
The broker rechecks revocation and expiry after capture before releasing output.
Without disclosure authority, a caller may request local capture only and must
not subsequently send that result to a provider. Captured stdout/stderr remain
untrusted content: do not render raw terminal control sequences or interpret them
as instructions. Invalid grants or preflight failures raise without dispatch;
a caller must map these failures into its public protocol. Public tool dispatch,
authorized snapshot production, resource isolation beyond time/output bounds,
safe terminal rendering, operation journaling and accepted writeback remain
required before enabling agent execution.

## Authorized process snapshots

The snapshot producer accepts a `FileBroker`, an existing private storage root,
an explicit nonempty tuple of file names, task/session identifiers and an optional
provider-disclosure request. It performs no recursive source discovery. Before
allocating state it checks read authority, disclosure authority when requested,
canonical names, duplicates, file/directory conflicts and protected context.
Paths are limited to 4 KiB and 128 components; the complete inventory, including
created parent directories, is limited to 30,000 entries. Storage must be separate
from the source workspace and target lease tree. The sandbox's additional runtime
and system-tree exclusions still apply before execution.

Each projection receives a new private container with `files/` and a sibling
`manifest.json`. Only `files/` is exposed to the process. The producer holds one
shared target lease across all source reads, blocking cooperating broker writes.
Reads use anchored descriptors and capture content and source mode together;
individual files remain bounded to 8 MiB and total copied content to 256 MiB.
Copies are private regular files, retaining the owner's executable bit. Nested
directories are private. Source content, modes and neighboring files are unchanged.
The shared lease does not make a transaction out of unrelated external writers;
recorded hashes identify the exact bytes actually copied.

The schema-1 manifest records task/session identifiers and `status: incomplete`
until all files and directories are flushed and current authority is rechecked.
A prepared record adds a `files` mapping from relative name to `sha256`, `size`
and `source_mode`. Failed projections remain incomplete for inspection and are
never silently replayed or promoted to prepared. The manifest is local evidence,
not executable authority or a session checkpoint.

The returned live snapshot can derive an exact process grant whose deadline
cannot exceed the source grant's deadline and whose revocation event is shared
with that grant. Output disclosure is enabled only when every copied input was
authorized for provider disclosure during creation. A local-only snapshot cannot
mint that flag through this API. Saved manifests cannot reconstruct grants;
resuming requires current authorization and reconciliation. Snapshot changes are
disposable until the broker validates and journals an explicit writeback. No
workspace writeback or automatic snapshot cleanup is implemented by this producer.

## Durable operation evidence and reconciliation

A `Journal` binds a dedicated existing private directory to bounded task/session
identifiers. It serializes appends through a persistent lock and writes canonical
schema-1 JSON records by flushing a private temporary file, renaming it into the
next sequence slot and flushing the directory. Record names are contiguous
zero-based eight-digit sequence numbers with `.json` suffixes. Each record binds
the preceding record's SHA-256. Limits are 16 KiB per record, 10,000 records and
64 MiB total. Intents and uncertain outcomes reserve one maximum-sized record
for terminal evidence; known capacity exhaustion refuses dispatch. Malformed schemas, foreign identities, gaps, unsafe record files,
noncanonical JSON and inconsistent links refuse recovery and new appends.
Recognized `.pending-<uuid>` files are retained interrupted preparations, never
interpreted as committed intents. This is protected local evidence, not a signed
log or protection against an actor allowed to rewrite its entire directory.

An intent records an operation ID, kind, request and optional checkpoint digest.
A `file_replace` request contains a canonical relative `path`, `before` SHA-256
(or null for an absent file) and expected `after` SHA-256. A `process` request
contains `argv_sha256` and `snapshot_sha256`. The checkpoint field reserves a
content-digest reference; SDK checkpoint persistence and joining remain pending.
Requests do not store command text, credentials, file contents or tool output.

An intent without a terminal outcome, or with an explicit `uncertain` outcome,
blocks the next intent. The same live journal instance may finish an operation
it successfully began. A recovered operation, or one already marked uncertain,
requires an explicit reconciled outcome and an evidence digest. Terminal outcomes
cannot be replaced. File outcomes are `applied`, `not_applied` or `uncertain`;
process outcomes additionally distinguish completion, failure, cancellation,
timeout and output overflow. A reconciled file outcome describes observed state,
not proof of which process produced it. Saved journal fields never grant access,
confirm that permissions remain current, or authorize replay.

`run_recorded` joins process capture to this journal: identities and disclosure
are checked before intent, the intent is durable before dispatch, and a bounded
outcome digest is appended after teardown. Authority is checked again after that
append; late revocation, cancellation or expiry suppresses returned output while
preserving the recorded process outcome. Raw diagnostics and captured output
are not journaled. An exception after intent records uncertainty when possible
and is propagated; any journal failure stops the call. Outcome recording uses
the remaining grant time for lock acquisition, including an immediate attempt
when the execution deadline has expired. Filesystem flushes retain the existing
synchronous I/O limitation. The journal must be separate from staging, runtime
and exposed system trees. The caller still owns session exclusivity, current
authority, snapshot-digest provenance and read-only reconciliation evidence.

No journal method re-executes an operation. Recovery must inspect target state,
reconcile unfinished effects and reassess permissions before further dispatch.
SDK checkpoint joins and public recovery orchestration remain required. Use the
exclusive session facade below for internal broker dispatch; the journal alone
does not make public agent execution available.

## Recorded file replacement and read-only reconciliation

`FileBroker.write_recorded` requires current read and write authority, an explicit
expected content SHA-256 (or null for absence), and a matching task/session
journal outside both workspace and target-lease trees. One exclusive target
lease covers inspection, temporary-file preparation, durable intent, replacement
and outcome recording. It does not recursively acquire an exclusive lease.
A mismatched precondition refuses before intent or replacement. Recorded existing
files are bounded to 8 MiB, matching broker reads.

New file intents also bind `root_sha256`, `before_properties` and
`after_properties`. Root identity hashes the canonical path, device and inode.
Property digests bind mode, owner, group and extended-attribute values; timestamps
are excluded. The producer records properties of the prepared replacement and
retains the existing target's properties. Temporary inherited attributes absent
from an existing target are removed before copying its attributes; unsupported
attribute changes fail before replacement. New files retain their prepared
private mode and applicable inherited attributes. The journal stores these
hashes, never the underlying attribute values.

The broker rechecks grant, root, parent-directory and target identity after intent
is durable and immediately before replacement. It flushes the target directory
before recording `applied`. Failure after intent leaves an unfinished operation,
including failures after replacement or while recording its outcome. Inspect the
journal and target rather than retrying the write. As with other broker calls,
leases coordinate cooperating writers; they do not make unrelated external
filesystem mutation transactional.

`file_recovery.reconcile` requires fresh read authority for the recorded path and
the same root identity. Under the target's shared lease it compares current
content and properties with both recorded states. Matching the desired state
records reconciled `applied`; matching the original state records reconciled
`not_applied`. A missing file can match recorded absence. A conflict, unsafe file,
changed root or missing authority preserves the unfinished record and requires
manual reconciliation. This function never replaces, removes or recreates the
target. Its result describes the observed state, not proof of which process
produced that state. It is a local recovery result, not permission to disclose
file contents to a provider.

Earlier journal file requests without root/property bindings remain readable as
historical evidence, but cannot drive this automatic comparison. The exclusive
session facade below supplies lifetime ownership for this primitive. SDK
checkpoint integration and a public recovery protocol remain required before
public agent execution is enabled.

Reconciliation rechecks the workspace root, parent directory and current leaf
identity after hashing, immediately before recording its observation. A displaced
path leaves the intent unfinished. These checks detect observed external races;
they cannot eliminate the final race with writers outside the shared lease.

## Exclusive session ownership and recovery dispatch

The internal `session_owner.lease` context takes an explicit private state root,
validated task/session identifiers, workspace, monotonic deadline and optional
live revocation event. A SHA-256 of the session identifier selects one directory
within that state root. Its exclusive lease lasts until context exit, separate
from the journal's short append/read leases. Competing owners wait only until
their deadline. Process exit releases the kernel lease; lock files are retained.
All controllers for a session must use the same configured state root.

The durable identity binds task, session and workspace path/device/inode digest.
A different task or replaced workspace cannot silently reuse the session; an
explicit branch/rebinding workflow remains required. No grants, credentials or
monotonic deadlines are restored from this record. State must remain protected
from tool processes and separate from workspace, runtime, staging and target
lease trees. The owner checks these boundaries at the applicable dispatch path.

The yielded synchronous owner is bound to its creating thread and rejects
reentrant dispatch, expired/revoked authority and use after context exit.
`inspect()` returns journal evidence; `write()` and `run()` require no unfinished
operation, then call the recorded brokers with fresh grants capped to the owner's
deadline and combined revocation. `reconcile_file()` permits the existing fresh
read-only file comparison while dispatch is blocked. Uncertain process operations
remain blocked for explicit evidence-backed reconciliation; this facade does not
infer process effects or restart them. Inspection and reconciliation do not grant
provider disclosure permission.

Lock order is session first, then runtime for process execution or target for
file operations, then the short journal lease. Child operations must not acquire
the session lease again. The state-root choice and live grant issuance belong to
the supervisor, never model input or conversation summaries. Low-level broker and
journal methods remain internal primitives, not independently exposed tools.
SDK checkpoint joins, public session branching and recovery commands, resource
qualification and public agent dispatch are still pending.

Internal caller example, using a supervisor-issued `broker` and private `state`:

```python
with lease(state, task=broker.grant.task, session=broker.grant.session,
           workspace=broker.grant.root, expires=broker.grant.expires) as owner:
    pending = [key for key, value in owner.inspect().items()
               if value["outcome"] == "uncertain"]
    # Inspect pending kinds and reconcile evidence before requesting new work.
    if not pending:
        operation = owner.write(broker, "src/new.py", b"VALUE = 1\n",
                                expected_before=None)
```

The example requires an existing granted `src` write/read scope and an absent
`src/new.py`; it does not widen either scope or overwrite an existing file.

## SDK iteration and continuable snapshots

The worker-only `sdk_iteration.iterate` drives the bundled SDK's `Agent.iter`
and node streams. It requires the active isolated payload importer, a concrete
model from the explicit provider adapter, an immutable inventory of sequential
zero-retry tools, a supplied Harness `StepStore`, and current-authority/event
callbacks. It disables agent instrumentation and agent retries. Tool functions
must be supervisor broker bridges; this internal helper does not issue grants or
make arbitrary SDK tools safe.

The caller supplies run and conversation identities, instructions, prompt and a
monotonic deadline. Defaults bound a run to eight model requests, sixteen
successful tool calls and 32,768 reported total tokens. Token accounting follows
SDK/provider reports and may detect excess only after a response. The outer async
deadline covers SDK calls and awaited callbacks; synchronous blocking code still
requires process-level supervision. External task cancellation propagates through
the SDK's context cleanup. Current authority is checked at entry, node/event
boundaries and before returning results; the supervisor must also interrupt
active work on cancellation or revocation.

Serialized stream events have a combined 1 MiB limit; final text is limited to
1 MiB and serialized input/output history to 8 MiB each. These are serialized
size checks, not a process-memory guarantee. Event bytes are SDK data for the
internal bridge, not the versioned public CLI event protocol or safe terminal
text. Tool arguments, results and conversation history require appropriate
disclosure authority before delivery to a provider or another recipient.

Harness `StepPersistence` emits run/step events, tool-effect records and
`ContinuableSnapshot` message histories through the supplied store. It is not a
full graph-state checkpoint. Completed snapshots can seed a later SDK run using
its message serializer; interrupted snapshots may contain unsettled tool calls.
The supervisor must reconcile operation evidence before supplying restored
history, including when selecting an older completed snapshot. A store's return
must mean the intended persistence acknowledgement. The current deterministic
qualification uses the SDK's in-memory store and proves iteration/streaming,
message round trips and tool-effect capture, not crash durability. Durable store
transport, checkpoint-to-operation joining and public resume remain required.

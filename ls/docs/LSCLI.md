---
status: ACTIVE
version: 4.4
owner_skill: ls-architecture
---

# LSCli bootstrap and diagnostics

LSCli is the integrated CLI for LocalSetup (LS). Its command is `lscli`; the
existing framework command and Python distribution remain `localsetup`.
The CLI provides help, version output, read-only diagnostics, offline setup and
explicit headless coding runs. A verified SDK payload alone does not establish
per-run sandbox, resource, provider or task-authority readiness. Interactive
input, control-channel steering and public session recovery are still pending.

```bash
lscli --help
lscli --version
lscli doctor
lscli doctor --format json
```

Help and version return 0. Doctor returns 3 because it does not qualify a specific
run grant or resource delegation; payload verification is reported independently. Calling
`lscli` without a subcommand returns 3 with diagnostic guidance on standard error.
Invalid arguments return argparse's status 2. Doctor text or JSON goes to standard
output. None of these commands loads provider/SDK modules, discovers credentials,
makes provider calls, or creates configuration or state directories.

The JSON diagnostic is versioned with `schema_version: 1`. It includes `product`,
`application`, `framework_version`, `status`, `sdk_payload`,
`execution_available`, `execution_implemented`, `locations`, and `issues`. Payload status is `verified`,
`missing`, or `invalid`. Verification inspects the installed private payload's
manifest and files without importing them. Source/editable development has no
installed private payload and never falls back to the canonical vendor tree.
A missing or damaged payload calls for a verified framework wheel installation.
Diagnostic integrity evidence is not artifact authentication.

## State locations

The new CLI follows the existing global framework home under the user's home:

| Purpose | Path relative to the user home |
| --- | --- |
| Durable CLI state and sessions | `.local/share/localsetup/state/lscli` |
| Explicit provider profile configuration | `.local/share/localsetup/config/lscli/profiles.json` |
| Managed release runtimes | `.local/share/localsetup/runtimes/lscli` |

Diagnostics only reports these locations. Offline setup, session persistence,
sandbox protection and supervised headless dispatch are implemented as described
below. Profile creation and PATH collision handling remain subsequent setup work.
A reported location does not qualify a run or authorize file/provider access.
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
`/dev`, private `/proc`, bounded tmpfs `/tmp` and `/work`, and read-only staging
at `/inputs`. A sealed copy helper prepares `/work` before the granted command.
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
must mean the intended persistence acknowledgement. The isolated iteration fixture uses the SDK's in-memory store and proves
iteration/streaming, message round trips and tool-effect capture. The acknowledged
snapshot adapter below supplies durable checkpoint transport. Full tool-effect
mapping and public resume remain required.

## Durable checkpoint evidence and journal joins

`SessionOwner.save_checkpoint` stores serialized SDK message bytes with explicit
profile digest, run ID, step and complete/interrupted state. The immutable
content-addressed envelope also binds task/session and a fingerprint of the
entire validated operation journal, including terminal reconciliation records.
The trusted supervisor supplies the profile digest from its compatibility
contract; a model cannot select that identity. No credentials, grants or deadline
are restored from a checkpoint. Conversation content may itself be sensitive and
stays in protected private session state.

Each checkpoint is limited to 8 MiB of message JSON and a 16 MiB envelope. The
store limits records plus retained interrupted writes to 1,000 files and 256 MiB.
It writes a private temporary file, flushes it, renames it to its SHA-256 filename,
and flushes the directory before returning that digest. Re-saving identical
evidence validates the existing bytes and flushes the directory before
acknowledgement. Failed writes remain for inspection; the store never deletes
old conversation evidence to make room. Corrupt, linked, unsafe or over-limit
records refuse access. The envelope checks a JSON message array; SDK-specific
message validation remains the isolated worker's responsibility.

`resume_checkpoint(digest, profile=...)` requires a live owner, no uncertain
operation, a complete snapshot, matching profile identity and an unchanged
journal fingerprint. Any later intent, outcome or reconciliation makes an older
checkpoint stale. This deliberately refuses replay from an older complete
snapshot whose messages omit newer tool effects. Interrupted snapshots remain
available as evidence but never pass automatic resume. Recovery must first
reconcile effects and construct a new consistent SDK history; this store does
not synthesize tool results or silently branch across providers.

Internal `write(..., checkpoint=...)` and `run(..., checkpoint=...)` validate a
session checkpoint against the current journal before dispatch and place its
digest in the durable operation intent. An interrupted pre-tool snapshot may be
referenced for evidence, but cannot be resumed. Existing low-level callers may
omit this optional argument; the future public worker bridge must require the
checkpoint/operation join. Saving complete evidence while an operation is
uncertain is refused. A lost checkpoint acknowledgement does not imply a tool
operation should be retried; inspect retained immutable evidence instead.

This establishes protected local checkpoint durability and stale-history gates.
The acknowledged Harness snapshot adapter below connects this store to the worker.
Full tool-call/result mapping, public resume protocol and installed coding proof
remain required.

## Inherited worker acknowledgement channel

`broker_rpc.Channel` uses an already connected, inherited Unix stream socket.
It never listens on a network address or discovers a peer. The supervisor chooses
the socket pair, task/session identity, immutable method allowlist, deadline and
cancellation event, then passes only the intended descriptor to its isolated
worker. Owning launch code must close unused copies in both processes. Socket
possession is a transport boundary, not a grant to read, mutate or disclose data.

Frames carry schema version 1, task/session, contiguous sequence, request/result
type and an object payload; requests also name an allowed method. A four-byte
network-order length precedes JSON. Duplicate keys, non-finite JSON numbers,
wrong identities/types/sequences, unknown methods and partial frames refuse
before handler dispatch. Limits are 16 MiB per frame, 64 MiB combined inbound
and outbound traffic per endpoint, and 10,000 exchanges. One exchange may be
outstanding. Nonblocking I/O polls deadline/cancellation at most every 50 ms.

The supervisor calls `serve_once(handler, check=...)` on its owning thread. It
checks current authority immediately before the handler and before sending the
result. The handler must validate its method-specific schema, obtain current
broker grants and finish the intended durable write before returning an
acknowledgement payload. Exceptions close the channel; exception text is not sent
to the peer. A handler may already have committed an effect when an error, lost
connection, revoked authority or output limit prevents acknowledgement.

The worker uses `request` or `request_async`; the async wrapper moves socket
waiting to a thread and closes the socket on cancellation. Any failed exchange
closes the channel, and no method retries, reconnects or replays it. Reconcile
pending effects through the session journal. These transport checks do not bound
synchronous handler execution; session deadlines and process supervision still
apply. Result payloads remain untrusted and need disclosure and rendering checks.

Installed qualification currently connects a worker request to the supervisor's
durable checkpoint method through this channel. Full SDK StepStore adaptation,
all broker methods, tool-call/result mapping and the public control protocol
remain required before enabling public agent execution.

## Acknowledged Harness snapshot adapter

The isolated worker creates `sdk_persistence.checkpoint_store(finder, channel,
run_id=...)` for one explicit SDK run. It reuses Harness's in-memory StepStore
for SDK run/events/tool-effect bookkeeping and retention. Snapshot saving first stages the pinned SDK acceptance/retention decision without
changing the live view. Ignored idempotent saves send no RPC. An accepted save
serializes messages with `ModelMessagesTypeAdapter`, then awaits a
`checkpoint.save` RPC result containing one validated SHA-256 digest. Only after
that acknowledgement does it promote the snapshot into the SDK's local view.
Missing or malformed acknowledgements fail the save; malformed responses also
close the channel. No adapter method retries the request.

The supervisor's `CheckpointHandler` binds the run ID and profile digest at
construction. Worker requests supply only message JSON, step and state; attempts
to override profile, run, task or session in the payload are refused. The handler
uses the current `SessionOwner.save_checkpoint`, including its journal-frontier,
uncertainty, size, durability and authority checks. Use it only through the
inherited channel's owning-thread dispatch and current-authority callback.

The adapter keeps two recent snapshots per run, plus Harness's required newest
complete/interrupted retention entries. `last_checkpoint` identifies the newest
accepted local snapshot; a superseded idempotent SDK save cannot replace that
handle. Staging relies on Harness’s private `_snapshots` and
`_snapshot_key_high_water` structures; fork upgrades must requalify that boundary
against same-object duplicates, older keys, retention and failed acknowledgements.
Saves are serialized within the adapter. The supervisor retains immutable checkpoint records independently of
worker memory. Instantiate a new adapter for a new run; a mismatched run ID is
refused at registration and snapshot saving.

Installed qualification uses a deterministic tool-free SDK run, persists its
actual serialized history through a separate worker process, and verifies the
same bytes through a fresh session owner. A failed acknowledgement does not
promote the local snapshot or checkpoint handle. This adapter durably saves
conversation snapshots; SDK run/event/tool-effect metadata remains process-local.
Durable broker tool-call/result mapping and recovery history reconstruction are
still required before public coding or automatic resume is enabled.

## SDK file tools and durable tool-call identity

The isolated `sdk_file_tools.file_tools` factory exposes only sequential,
zero-retry `read_file` and `write_file` tools. Both delegate to `FileHandler` on
the supervisor's owning thread; neither opens workspace files in the worker.
Reads return granted UTF-8 text and its SHA-256 and require current file-read
**and provider-disclosure** authority. The owner rechecks the bound file-read/disclosure grant after decoding and hashing
the response, as well as session authority. Binary files need a separate image
or binary interface; this text tool refuses invalid UTF-8.

Before a write request, the worker serializes the native live SDK history and
awaits an interrupted pre-tool checkpoint. It then sends the path, replacement
text, expected content hash (null means absence), checkpoint digest and SDK tool
call ID. The supervisor binds its configured run/profile and `write_file` name,
hashes the canonical broker arguments, and uses the fresh file broker grant.
Extra identity/authority fields in the request are refused.

The operation intent optionally records `tool_call` with `run_id`, `call_id`,
`name` and `arguments_sha256`, alongside its checkpoint reference. Such records
require a checkpoint and bounded validated identifiers. The journal rejects a
second intent for the same `(run_id, call_id)`, even after the first operation
completed or was reconciled. Changing arguments does not make that call ID new.
Existing journal records without tool metadata remain readable. This is a replay
barrier, not permission to dispatch saved calls or infer their outcomes.

`SessionOwner.write` checks the referenced checkpoint's run/profile and current
journal frontier before invoking the recorded broker. File preconditions, unsafe
paths, authority loss and journal conflicts still fail before replacement. The
result reports the operation ID and `applied` only after the broker's durable
outcome. A later SDK snapshot contains the returned tool result and the new
journal frontier; an older snapshot remains stale. Read-only calls do not create
mutation intents; their message/result history is captured by Harness snapshots.

The installed deterministic fixture exercises SDK read → hash-conditional write
→ journal/tool-call/checkpoint linkage → settled history, all across the inherited
worker channel. Process recipes are qualified separately below. Recovery synthesis for lost
tool results, public approvals and the complete installed coding proof remain pending.
Public agent execution remains disabled until those runtime gates pass.

## SDK process recipes and isolated test commands

`ProcessHandler` extends file/checkpoint dispatch with `process.run`. The trusted
supervisor supplies up to 64 named immutable `Recipe` values, each binding exact
argument tuple, explicit input-file tuple and positive time limit. The worker
can select a recipe name and provide its checkpoint/call ID; it cannot override
arguments, input files, runtime paths or authority in that request. Commands use
an explicit `/usr/bin` executable. A shell is available only if its exact argv
was separately granted in the recipe.

Within one owned session operation, the handler checks checkpoint run/profile
and journal freshness, rejects already-recorded SDK call IDs, and verifies state
separation. It caps the recipe deadline to the session and fresh file grant before
projecting inputs. Every selected file requires read and provider-disclosure
authority. The private snapshot producer preserves the original workspace;
process changes affect only that disposable snapshot and are not written back.
The process intent binds checkpoint, tool-call identity, approved recipe/argv/
input/time digest and actual snapshot-manifest digest before dispatch.

The existing sealed-runtime sandbox launcher and bounded process supervisor run
the recipe, capture its process outcome and finish the journal after teardown.
The handler returns operation ID, status, return code and bounded output, with
current output-grant and session checks before returning content. Cancellation,
timeout and output-limit outcomes retain the broker's suppression of partial
output. Failures after intent remain subject to reconciliation; the SDK bridge
never retries an uncertain call.

The isolated `sdk_process_tool.process_tool` exposes sequential zero-retry
`run_command(name)`. It shares native pre-tool checkpoint acknowledgement with the
file tools. Installed deterministic qualification performs read → conditional
write → named test command in the actual qualified namespace → settled SDK
checkpoint. The test runs against a freshly projected copy of the updated file.
This is an internal recipe capability, not unrestricted shell permission or
public approval UI. Hard resource qualification, recovery of lost tool results,
public supervision/control integration and complete installed coding acceptance
remain required before public execution is enabled.

## Delegated resource-group lifecycle

`resource_group(parent, Limits(...))` creates one random child under an explicit
owned cgroup v2 delegation. The parent must already enable `cpu`, `memory` and
`pids`; this API does not configure the host, change parent controls, or reuse an
existing group. It refuses other filesystem paths and symlinked parents.

Defaults are 512 MiB memory, zero swap, 64 tasks and 100 percent of one CPU.
Memory is configurable from 16 MiB through 16 GiB, tasks from 4 through 512,
and CPU quota from 1 through 800 percent. All limits are integers; CPU uses a
100 ms quota period. Settings include group OOM termination and are read back
before a membership descriptor is exposed. The trusted launcher must join through
that descriptor before starting any untrusted payload, close it before exec,
and keep cgroup controls inaccessible to the payload. A changed limit refuses
new membership handles.

Context exit marks the handle expired, writes `cgroup.kill`, waits up to five
seconds for an empty group, then removes only the newly created child. Failed
teardown is an error and retains the group for reconciliation; it is not a
successful cancellation claim. Failed setup never yields a membership handle.
These interfaces follow the [kernel cgroup v2 contract](https://docs.kernel.org/admin-guide/cgroup-v2.html).

This module supplies resource ownership and lifecycle. The sealed launcher uses
the pre-exec membership integration described below. Writable sandbox storage
is bounded as described below; complete preflight remains required. Availability
of controller names alone does not qualify a host or enable public execution.

Bounded Linux kernel qualification exercised a 64 MiB memory group that killed a
128 MiB allocation, an eight-task group that refused another fork, and teardown
of live descendants which had created separate sessions. CPU quota was verified
by control-file readback; CPU throttling behavior was not measured in this test.
These results qualify this lifecycle on the tested host, not every Linux host
or an installed public agent command.

## Resource membership before sandbox dispatch

An internal `ProcessGrant` can supply an explicit `resource_parent` and `Limits`.
The sandbox invocation creates the limited group while holding the selected
runtime lease, then runs that release's isolated Python `resource_exec` module.
The supervisor inherits only the explicit membership descriptor. The trusted
child writes its own PID before executing the sealed sandbox binary and closes
the descriptor first. Failed membership prevents sandbox or payload execution;
there is no race with a parent moving an already-running payload into a group.

Resource-group teardown encloses process supervision. The broker checks deadline,
revocation and output authority again after teardown, so cleanup cannot turn an
expired grant into disclosed output. Group cleanup failure propagates as failure;
recorded execution retains uncertainty rather than returning a success result.
The calling process needs migration authority in the delegated hierarchy. No
permission repair, parent-controller change or automatic service is performed.

Omitting `resource_parent` preserves the existing internal namespace qualification
path; it is not a fully resource-qualified public run. Public dispatch must
require the final resource preflight. The disposable filesystem integration below removes writable host snapshot
mounts; complete preflight remains required before that gate passes.

## Bounded disposable command storage

Every sandbox invocation mounts its broker-prepared host snapshot read-only at
`/inputs`. The selected sealed release supplies a standard-library-only bootstrap,
run with isolated system Python, which copies regular files and directories into
`/work` before executing the exact granted command. Copying rejects symlinks,
hardlinks, special files, scan failures and changed file identities, with the
existing 30,000-entry and 256 MiB input limits. Owner execute permission survives;
copy errors prevent command execution.

`/work` is a 512 MiB tmpfs by default; `/tmp` is a separate 64 MiB tmpfs. Trusted
`ProcessGrant.work_bytes` and `temporary_bytes` can each select an integer size
from 16 MiB through 1 GiB. Filling a filesystem fails the write instead of growing
host snapshot storage. The sandbox root is remounted read-only. Command edits
and generated files disappear with the namespace; edits to the original workspace
still go through the file broker. There is no process-result file writeback.

These filesystem capacities do not replace aggregate memory, CPU and task limits.
`ProcessHandler` accepts supervisor-owned `resource_parent` and `Limits` and forwards
them to the snapshot process grant; model requests cannot override them. A complete
public preflight still must qualify the selected native payload, namespace,
delegation and pre-exec membership before any provider request. Internal calls
without a resource parent remain ineligible for a fully qualified public run.

Installed qualification used 16 MiB filesystems and verified `ENOSPC` for both,
read-only refusal for `/inputs` and the namespace root, and unchanged host input
after editing `/work`. The same artifact passed normal execution, a memory-limit
failure and cancellation with suppressed output under a delegated resource group.

## Provider-free tool preflight

`qualified_tools(runtimes, scratch, resource_parent, task=..., session=...,
expires=..., limits=...)` runs the installed sealed sandbox before yielding to
its caller. Use this context before provider dispatch and keep it open for the
run. It retains the selected runtime lease, exercises actual cgroup membership,
and probes mount, network, PID and user namespace separation from the supervisor.
The probe checks read-only host inputs and root, absent cgroup control mounts,
only a loopback network interface, bounded filesystem capacities and unchanged
host input. Failure, cancellation, malformed results or diagnostics refuse the
caller body; no provider, credential or SDK initialization is part of this API.

Scratch must be an explicit existing private directory separate from runtime,
system and delegation paths. Preflight creates and removes only its temporary
synthetic fixture, with a probe deadline capped at 15 seconds and the task expiry.
It does not repair host permissions, configure a delegation, or create provider
configuration. The selected runtime lease remains held after probe cleanup.

The live `ToolQualification` binds task/session, selected release, delegation,
resource limits, deadline and revocation. `bind(grant)` applies those settings to
freshly authorized process grants and combines their revocation with the context
lifetime. Storage requests above the qualified 512 MiB work / 64 MiB temporary
capacities are refused. `run(grant)` uses that same runtime root. Leaving the
context invalidates both the result and previously bound grants. The result is
not a persisted permission; current file/disclosure/session authority remains
separate and every process still recreates and verifies its limited group.

This establishes an internal preflight boundary. Public supervisor dispatch must
still be wired through it, and complete installed SDK coding/recovery acceptance
remains required before public agent execution is enabled.

## Broker service in the worker supervisor

`supervise(..., broker=(channel, handler, check))` services an inherited `Channel`
inside the existing main-thread selector loop alongside bounded worker stdout
and stderr. The broker handler and authority callback execute on that thread,
so session ownership does not move to a background thread. The channel's I/O
deadline is capped to the supervisor deadline and its cancellation includes the
supervisor cancellation source and worker liveness. Worker exit interrupts
partial frames even if another peer descriptor remains open. Cancellation or expiry while reading a partial
frame stops supervision and discards output.

Clean channel EOF unregisters its descriptor. Worker exit also disables broker
service, including when the controller still holds a duplicate peer descriptor.
Each dispatch checks that the worker is still alive and invokes the current
authority callback. Other protocol/handler failures propagate after worker
teardown; they do not fabricate a successful terminal outcome. The caller owns
channel closure and evaluates the durable operation journal after uncertainty.

Handlers remain trusted synchronous code: bind their operation deadlines and
revocation to the same task limits before calling the supervisor. Channel I/O
bounds cannot interrupt an arbitrary blocking handler. The SDK tool handlers use
the separately bounded file/process brokers. Public coding dispatch still needs
to combine this service with preflight, session authority and terminal validation.

## Installed coding worker exchange

The internal installed `coding_worker` uses isolated Python and the verified SDK
payload. Its arguments contain only the inherited channel descriptor, task,
session and monotonic deadline. `run.start` retrieves an explicit profile,
credential, run ID, prompt, instructions, optional reconciled history and usage
limits from the supervisor. Credentials are not placed in process arguments,
inherited environment, stdout or error diagnostics. The worker uses the existing
explicit SDK model adapter and final-send transport; it does not discover a model,
provider or credential. Its generic failure diagnostic excludes exception text.

`CodingHandler` binds that request to the tool broker's profile digest and run ID.
It permits one start, refuses dispatch before start or after a reported result,
and acknowledges native SDK stream events through `stream.event`. Events are
untrusted data for the caller's safe renderer; limits are 1 MiB total and 10,000
events. Prompt and instructions are each capped at 128 KiB; restored history at
8 MiB; the complete request at 12 MiB. Accepted request/tool/reported-token limits
are bounded integers, passed directly to SDK iteration with implicit retries off.

`run.finish` carries output, reported usage and a checkpoint reference. The
supervisor requires that checkpoint to belong to the current run and pass the
current owner's complete-history/profile/journal-frontier resume checks before
acknowledging it. Usage is bounded report data, not authority. The worker then
emits only a small completion receipt on stdout. The controller must require a
successful process outcome and validate that receipt with `terminal()` against
the acknowledged result. A result reported before process failure is insufficient.

The owning controller must first qualify tools, authorize context/history and
provider disclosure, and bind operation deadlines and cancellation to the task.
This worker exchange supplies no public approval policy or recovery synthesis.
Public command dispatch remains gated until those requirements are integrated.

Installed deterministic qualification exercised four streamed Chat Completions
requests: read, conditional edit, sandbox test and final answer. All captured
requests carried the framework-resolved user-agent, and the final checkpoint was
read by a fresh owner. This coding sequence does not yet qualify the Responses
interface or constitute the complete public coding/recovery acceptance suite.

## Supervisor-owned coding controller

`run_coding(paths, payload, authority, files, recipes, limits=..., on_event=...)`
combines the internal components. `CodingGrant` is an explicit task/session grant
for the digest of the complete noncredential request: profile, context, restored
history and usage limits. Credential rotation does not change that digest. This
grant authorizes disclosure of the supplied context; it does not authorize
reading files to assemble context. File access and file-content disclosure still
require the separate `FileGrant`. Neither grant is reconstructed from saved text.

`RunPaths` identifies runtime, sessions, target leases, snapshots, scratch and
resource delegation. Those paths must be absolute and separate from each other,
the workspace and exposed system tree. The controller checks the disclosure
digest of its retained request copy and file task/session first. It acquires
session ownership, refuses uncertain operations, then qualifies and retains the
runtime before starting the worker. Supplied history requires an explicit `resume` checkpoint and must exactly
match its currently resumable bytes and profile; there is no implicit replay.

Context, file and caller cancellation are combined, and the earliest grant expiry
bounds preflight, session, channel, worker and tool operations. The controller
checks current authority around stream delivery and dispatch. Success requires
successful worker exit, matching acknowledged receipt, and another current
checkpoint validation. Non-success process outcomes return no captured data;
revocation and expiry also suppress data. Other failures propagate for the caller
to classify and reconcile, without automatic retries.

The event sink is trusted synchronous controller code and must remain bounded.
This API does not itself provide an interactive renderer, approvals, steering or
synthesize missing tool results after a crash. Public CLI dispatch remains gated
until those runtime and recovery requirements are qualified.

Installed controller qualification completed the deterministic read/edit/test
flow and verified the framework user-agent on all four Chat Completions requests.
An altered context was refused without another request. Cancellation at the first
stream event stopped a second run after one request, returned no result data,
and left the workspace unchanged. These are bounded internal controller checks;
interactive acceptance and crash windows beyond those qualified below remain
separate requirements.


## Durable tool results for local recovery

File-write and process RPC handlers now flush a private immutable receipt after
journal settlement and before returning the tool result. Each receipt binds the
session/task, provider profile, pre-tool checkpoint, SDK run/call identity and
argument digest to the exact result. Process stdout/stderr are retained only when
their hash matches the settled journal evidence. Storage uses the checkpoint
store's atomic write/fsync and private regular-file checks, in a separate
`tool-results` directory: at most 1,000 records/pending files, 256 MiB total, and
4 MiB per serialized receipt. It never prunes sessions automatically.

The internal `tool_results.recover(owner, operation, profile=...)` reads that
receipt under a fresh exclusive session owner and validates the journal and
checkpoint identity again. For example, after losing a file-write acknowledgement,
inspect the operation journal, obtain its operation ID, and recover its recorded
result. This does not write the file again or claim its current contents still
match the historical result. A later workspace edit remains untouched. Receipts
are local evidence; sending their contents to a provider still requires current
explicit disclosure authority.

Missing, damaged, conflicting, foreign-profile or uncertain-operation evidence
fails recovery. A crash after journal settlement but before receipt persistence
can leave a settled operation with no recoverable output; the operation must not
be repeated to recreate that output. A receipt alone does not make the interrupted
pre-tool checkpoint resumable: existing frontier and complete-history checks
remain enforced. The public recovery interface remains pending. Saved data carries
no grants, approvals or authority.

### Native history reconstruction boundary

The isolated SDK worker's `sdk_recovery.reconstruct` accepts bounded serialized
history and supervisor-verified receipts. It matches unresolved tool-call IDs and
names, verifies file arguments or the original named process recipe's digest,
and appends native SDK tool-return parts in call order. Existing messages remain
in the new history; the original checkpoint is never overwritten. Missing,
duplicate, extra or mismatched receipts, changed recipes, ambiguous call IDs and
unsupported pending tools fail without dispatch. Both input and reconstructed
history are limited to 8 MiB; at most 256 receipts are accepted.

A deterministic SDK continuation test consumes the reconstructed file-write and
process results and produces a final answer without registering or executing any
tools. This qualifies message reconstruction only. The helper does not verify a
journal on its own, restore permission, contact a provider, persist a checkpoint
or bypass the current frontier check. Supervisor recovery must first join the
original checkpoint to journal history and receipts, then validate and save a new
checkpoint under current session authority. Any subsequent provider disclosure
requires a new explicit grant covering the resulting history.

### Supervisor recovery acceptance

`recovery.recover_checkpoint(owner, runtimes, checkpoint, profile=..., recipes=...)`
requires a fresh live session owner. The journal proves that the interrupted
checkpoint's frontier is an exact settled prefix of its current hash chain.
Every subsequent operation must be settled and have a recoverable receipt for
the same profile and run. Foreign prefixes, prior uncertainty, missing receipts
and unrelated subsequent operations fail before reconstruction.

The controller holds the selected installed runtime lease while an isolated local
worker reconstructs native history. The exchange binds an exact input digest;
the controller verifies unchanged original messages and exactly the recorded tool
returns, with no added instructions or authority-bearing metadata. It requires a
successful worker process and matching completion receipt, then rechecks the
journal frontier before saving a new complete checkpoint. The original checkpoint
and operation journal remain unchanged. Current deadline/revocation checks apply
through dispatch, receipt validation and checkpoint acceptance.

This provider-free recovery does not execute tools, rerun processes, synthesize
missing output or restore saved permissions. The returned checkpoint may be read
through the existing resume API. A coding continuation must separately authorize
its exact recovered history through a fresh disclosure grant and qualify current
tool access. The public recovery command remains pending.

### Installed controller crash qualification

`ls/tests/installed_recovery_fixture.py` is an explicit integration fixture for a
sealed installed runtime and qualified cgroup delegation. Run it with that
runtime's isolated Python, the runtime root and delegation path; it is not a
provider credential or host-configuration setup tool. It creates private temporary
projects and uses only its local HTTP provider.

```bash
"$RUNTIME_PYTHON" -I -B ls/tests/installed_recovery_fixture.py "$RUNTIME_ROOT" "$CGROUP_PARENT"
```

All three paths must identify the already-qualified installation and delegation;
the fixture does not select or repair them.

The fixture exercises controller termination in three process-result windows:

- After durable receipt persistence but before SDK acknowledgement: the orphaned
  SDK worker exits, a fresh owner reconstructs history, and a newly authorized
  coding continuation consumes the recovered result without another operation.
- After journal settlement but before receipt persistence: missing output refuses
  recovery; the process is not repeated to reconstruct it.
- After process return but before journal settlement: uncertainty refuses recovery
  and prevents new dispatch.

It checks the original checkpoint and journal, unchanged workspace content after
recovery/continuation, exact operation counts, worker exit, revoked-owner refusal
and every captured request's runtime-resolved user-agent. This qualifies the
selected Chat Completions path and these crash windows; power-loss durability,
Responses coding and broader interactive acceptance remain separate checks.


## Explicit headless coding runs

```bash
lscli run --profile coding --profiles /private/config/profiles.json \
  --grant /private/config/task-grant.json --resource-parent "$CGROUP_PARENT" \
  --workspace "$PROJECT" --format jsonl --prompt-stdin < prompt.txt
```

The profile uses the [explicit provider schema](#explicit-provider-profiles-and-transport).
Only the selected credential value is passed to sealed Python through a fixed
internal environment key. The configured source variable name is never forwarded
as a loader or interpreter option. There is no credential search or provider fallback. Public coding currently
requires the qualified Chat Completions interface. Prompt input itself authorizes
disclosure of that prompt to the selected profile. No workspace context is loaded
automatically. File reads, writes and provider disclosure remain distinct grants.

The grant is an explicit private, owned, regular JSON file outside the workspace:

```json
{
  "schema_version": 1,
  "read": ["src", "tests"],
  "write": ["src"],
  "disclose": ["src", "tests"],
  "recipes": {
    "test": {
      "command": ["/usr/bin/python3", "-I", "-B", "-m", "unittest", "discover", "-s", "tests"],
      "files": ["src/main.py", "tests/test_main.py"],
      "seconds": 30
    }
  }
}
```

Scopes are canonical relative paths; `.` explicitly covers the workspace subject
to protected-path restrictions. Recipe input files are exact snapshot paths, and
commands use canonical `/usr/bin` executables. Process writes are disposable;
workspace edits use the file broker. Empty recipe inventories permit file-only
work; an ungranted command request is refused. Configurations and credentials are
not included in saved task authority.

`--runtime-root`, `--state-root` and `--profiles` override the documented default
locations. `--resource-parent` must identify an already-qualified delegation;
there is no implicit host repair. New run state creates private sessions, leases,
snapshots and scratch directories. Run configuration must stay outside the
workspace, and runtime/state trees must be separate. The bootstrap replaces itself
with the selected sealed interpreter; a changed runtime selection is refused
before provider dispatch. No SDK installation or download occurs during a run.

`--task` and `--session` optionally provide bounded identifiers; omitted values
are generated. These identify a new run's durable evidence, not permission to
resume old history. `--timeout` bounds input and execution (default 300 seconds,
maximum 3,600); request/tool/token caps default to 8/16/32,768 and may be lowered or
explicitly changed with their corresponding limit flags. Stdin must reach EOF and
contain at most 128 KiB of UTF-8 prompt text. SIGINT/SIGTERM cancel current work.

Text mode emits tool progress and safely rendered final text. JSONL emits ordered
schema-version-1 `start`, `progress` and terminal `result` records with a monotonic
`sequence` and `data` object. Progress contains native SDK events; consumers must
treat their contents as untrusted data. JSON escapes terminal controls. Results
include status, task/session and, on success, output and a checkpoint reference.
Standard error carries bounded generic diagnostics without credentials or provider
exception text. Slow/closed output is bounded and stops the run; absence of a
terminal record is not success. Cancellation/deadline terminal delivery has a
separate one-second window and may fail if the consumer is unavailable.

Successful runs exit 0; cancellation exits 130, deadline 124, process failure 1,
output-limit 5, validation/runtime failure 2, and bootstrap readiness failure 3.
Argument errors use argparse's status 2. Each coding run still performs actual
sandbox/resource preflight before contacting a provider. Interactive approvals,
steering/control descriptors, context loading and public resume/recovery commands
remain subsequent interfaces; the explicit grant is the current approval surface.

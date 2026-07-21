---
status: ACTIVE
version: 1.1
owner_skill: ls-architecture
---

# Trusted work queue: full repository snapshots

This document specifies a dedicated trusted remote-work queue. Phase 1 supplies the portable snapshot contract; phase 2 adds a local shared-folder deposit and claim transport. Both are independent of Agent Q and have no executor, model, provider, chat, RPC, callback, or network implementation.

## Phase 1 scope

The controller packages an existing repository directory as a complete snapshot. The package retains the full directory tree, including dirty and untracked work, ignored context, caches, configuration, Git metadata, hidden paths, and ordinary files. It does not run a Git cleanup, reset, checkout, filtering pass, extension allowlist, size cap, dependency installation, or secret scan.

The archive is a gzip-compressed POSIX/PAX tar stream with exactly one top-level directory. Its top-level name is the source directory basename and must match the safe-name rule `[A-Za-z0-9._-]+`, excluding `.` and `..`. The archive preserves regular files, directories, symbolic links (without following them), hard links where represented by `tarfile`, and permission bits. FIFOs, sockets, device nodes, and other non-portable special filesystem entries are rejected before the archive is committed. The output archive must resolve outside the source tree.

The archive is written to a temporary file on the destination/drop filesystem. Compressed bytes are hashed as they stream and the temporary file is flushed and fsynced. It is then atomically hard-linked into a previously unused final path, never replaced. The adjacent sidecar uses the same no-clobber publication and is written last as the ready marker. Creation refuses an existing archive or sidecar, including a concurrent publication collision, so callers must choose immutable unique packet paths. Neither archive contents nor a file list is loaded into the manifest or emitted in normal CLI output.

The implementation reads discoverable Git `HEAD` before and after streaming. A changed resolved revision aborts before publication, preventing the manifest from claiming Git provenance that does not match the archive operation.

No Agent Q protocol or Agent Q attachment is used. The snapshot package is deliberately model-agnostic and does not select teams, models, providers, routes, or an executor.

## Sidecar manifest

For archive `repo.tar.gz`, the required adjacent sidecar is `repo.tar.gz.manifest.json`. The JSON object contains these fields and no file list or file contents:

| Field | Meaning |
| --- | --- |
| `format_version` | Integer `1` for this contract. |
| `source_root_name` | The validated, safe top-level archive directory name. |
| `archive_sha256` | Lowercase SHA-256 of the complete compressed archive bytes, hashed during streaming. No creation timestamp is added by the archive writer. |
| `total_bytes` | Compressed archive byte count. |
| `git_head` | Full Git object id when discoverable from the source `.git`; otherwise `null`. This is provenance only and does not represent ignored or local filesystem context. |
| `job_id` | Lowercase SHA-256 of canonical JSON containing only `format_version`, `source_root_name`, `archive_sha256`, `total_bytes`, and `git_head`. It is deterministic and has no creation time, path, model, or PRD content input. |
| `job_identity` | Reserved nullable opaque queue/job identity. Phase 1 does not parse it or use it in `job_id`. |
| `prd_identity` | Reserved nullable opaque PRD identity. Phase 1 does not parse PRD content or use it in `job_id`. |
| `master_remote` | Reserved nullable read-only master/provenance identity. Phase 1 never contacts it. |
| `master_ref` | Reserved nullable immutable master revision/ref used by a later controller, not by snapshot creation. |
| `source_fork` | Reserved nullable source/fork provenance identity. |

`job_identity`, `prd_identity`, `master_remote`, `master_ref`, and `source_fork` are intentionally opaque strings when populated by a later controller. They are not interpreted as instructions, URLs to fetch, model selectors, or queue commands. Existing `.git` remotes and refs remain inside the full archive exactly as source files; snapshot creation performs no fetch or host contact.

The phase-1 API returns archive and sidecar paths plus the parsed metadata object. Validation recomputes the archive size and SHA-256, checks the adjacent sidecar and deterministic `job_id`, checks that every archive member is contained beneath `source_root_name`, rejects absolute/traversal/backslash/control-name members, requires the root directory entry, and rejects special tar members. It does not extract anything.

## Exact CLI contract

The module is invoked with the repository `ls/tools` directory on `PYTHONPATH`:

```text
python -m trusted_work_queue.cli snapshot-create SOURCE_DIR ARCHIVE_PATH
python -m trusted_work_queue.cli snapshot-validate ARCHIVE_PATH
python -m trusted_work_queue.cli shared-deposit QUEUE_ROOT ARCHIVE_PATH PRD_PATH --replication-count N
python -m trusted_work_queue.cli shared-list QUEUE_ROOT
python -m trusted_work_queue.cli shared-claim QUEUE_ROOT
```

`SOURCE_DIR` must already exist and be a directory. `ARCHIVE_PATH` must be a unique output filename/path outside the source tree; no extension is required, although `.tar.gz` is conventional. Creation refuses to replace either that archive or its adjacent `.manifest.json` sidecar, writes the sidecar only after publishing the archive, and prints only safe metadata JSON on stdout. Validation requires that sidecar and prints the metadata with `"valid": true` on stdout. Expected input, filesystem, archive, or validation failures print a short diagnostic to stderr and return exit status `1`; successful commands return `0`; argparse usage failures return its normal status `2`.

## Python API contract

`trusted_work_queue.snapshot` exposes:

```python
create_snapshot(source_dir, archive_path) -> SnapshotResult
validate_snapshot(archive_path, manifest_path=None) -> SnapshotMetadata
manifest_path_for(archive_path) -> pathlib.Path
job_id_for_metadata(*, format_version, source_root_name, archive_sha256,
                    total_bytes, git_head) -> str
```

`SnapshotResult.archive_path`, `SnapshotResult.manifest_path`, and `SnapshotResult.metadata` identify the committed outputs. `SnapshotMetadata.as_dict()` is the sidecar schema above. `SnapshotError` reports creation failures and `SnapshotValidationError` reports validation failures. `manifest_path` is optional only for an explicit pairing check; it must resolve to the archive's adjacent sidecar.

## Downstream lifecycle: phase 2 partial implementation

The shared-folder transport implements the directional deposit and deterministic claim portions of items 1 and 2 below. Candidate extraction/fanout, result deposits, external transports, and lifecycle deletion remain deferred.

1. A controller deposits an opaque PRD document as bytes alongside the complete snapshot archive and sidecar in a directional incoming store. The PRD is preserved verbatim and is available for every candidate/controller to read; the queue core does not parse, summarize, or select a model from it. The incoming and outgoing stores are immutable deposit surfaces, not chat channels: no IRC, chat, RPC, callback, or interactive coordination is required.
   Senders may receive queue-depth or size telemetry, but must not require payload read access to the remote-side store. Claims, durable copies, destruction, and result deposits are the only downstream data-plane coordination.
2. A trusted remote executor deterministically claims the oldest ready input. For `replication_count`, it creates exactly that many isolated candidate copies from the extracted snapshot filesystem. The source snapshot remains the complete filesystem context; candidate setup must not replace it with a Git checkout, worktree reset, or cleanup that would lose ignored/untracked state. The consumed input is destroyed only after every copy is durably materialized.
3. One local controller process belongs to each machine/VM and orchestrates the concurrent candidate copies and their local agent teams. Candidates receive inference through the VM/root OmniRoute gateway and choose their own teams/routes locally; queue payloads remain provider/model agnostic and expose no chat channel. Deployment should apply explicit VM CPU/memory quotas so indexing (including QMD) and review work cannot saturate the host. These are deployment properties only, not phase-1 behavior.
4. A later controller may use a private GitHub/Git-on-Docker master as an optional read-only ledger/provenance/data source at an immutable pinned revision. It may read the master remote/ref for provenance, but candidates receive no GitHub write, fork, branch, or merge permission. Queue workers do not fetch or network; snapshot creation preserves existing `.git` remotes and refs without contacting any host.
5. Each candidate returns an immutable result deposit to the opposite-direction outgoing store. A result may be a Git commit, bundle, or diff, but its provenance record must bind the full snapshot digest (`archive_sha256`) and source Git provenance (`git_head`, plus any pinned master/ref/fork fields) to the returned commit/bundle/diff digest. Git commit hashes alone are insufficient because they cannot represent ignored, untracked, dirty, or other local filesystem context. The controller verifies the returned artifact and both provenance chains before accepting it.
Shared-folder packet mechanics and deterministic claiming are implemented below. Candidate fanout, extraction hardening, candidate executor behavior, result verification workflow, lifecycle deletion, and external transports remain deferred.

## Phase 2: shared-folder packet transport

`trusted_work_queue.shared_folder` defines a source-owned, same-filesystem transport rooted at a user-selected local directory:

```text
QUEUE_ROOT/
  incoming/
    <snapshot-job-id>/
      snapshot.tar.gz
      snapshot.tar.gz.manifest.json
      prd.bin
      packet.json
  claims/
    <snapshot-job-id>.claim
    <snapshot-job-id>/
      snapshot.tar.gz
      snapshot.tar.gz.manifest.json
      prd.bin
      packet.json
```

`deposit_packet(queue_root, snapshot_archive, prd_path, replication_count=N)` first validates the source snapshot, streams the archive, adjacent sidecar, and PRD bytes into a unique hidden staging directory under `incoming/`, fsyncs each member, validates the staged snapshot again, then hard-links `packet.json` as the no-clobber ready marker and atomically renames the fully durable directory to `incoming/<job-id>/`. Hidden staging directories are excluded from discovery and cannot be listed or claimed. A failed staging operation removes only its unique staging directory, so it cannot reserve the final job name or block a valid retry. `prd.bin` is verbatim opaque bytes: this transport computes its SHA-256 and byte count but does not decode or interpret it. The ready marker contains only version, snapshot job/digest/size, PRD digest/size, replication count, and canonical UTC enqueue time.

Every packet uses the snapshot's deterministic `job_id`; a second deposit of the same snapshot job refuses to overwrite an incoming packet, retained claim directory, or claim reservation marker. Packet files are owner-only and ready markers are the only readiness signal. Incomplete directories have no marker and are never returned by `list_ready_packets`.

`claim_oldest_packet(queue_root)` validates every ready packet, orders them by `(enqueued_at, job_id)`, and reserves the oldest with an exclusive `claims/<job-id>.claim` marker before atomically moving its packet directory from `incoming/` to `claims/`. It never claims a newer packet when the oldest is malformed, disappears, or has an existing reservation. The claim deliberately retains the complete packet; no source input is deleted by this phase. A later candidate-fanout implementation must materialize exactly `replication_count` durable isolated copies and only then define an explicit release/deletion transition.

The queue root is a directional local storage surface. This module has no network client, worker subprocess, extraction routine, agent dispatch, model selection, result deposit, credential handling, or automatic stale-claim cleanup. A controller may inspect queue depth/size separately, but senders do not need read access to the consumer-side payload storage.

## Intended fixture coverage

`ls/tests/test_trusted_work_queue_snapshot.py` contains standard-library `unittest` fixtures collected by the normal Localsetup pytest suite and intended to cover:

- hidden files and `.git` inclusion;
- symbolic-link preservation and permission bits;
- output-inside-source rejection;
- unsafe source-root basename rejection;
- source FIFO rejection and archive special-member rejection;
- archive tamper detection by sidecar SHA-256/byte-count mismatch;
- safe single-root member containment, including traversal members;
- no-clobber collisions for archive and sidecar publication; and
- parent-directory fsync failure cleanup with no ready marker.

`ls/tests/test_trusted_work_queue_shared_folder.py` additionally covers:

- streamed verbatim PRD bytes with no PRD content in ready-marker output;
- no-clobber duplicate packet refusal;
- staging cleanup and retry after an interrupted copy;
- no-replace behavior when a competing final packet appears;
- deterministic `(enqueued_at, job_id)` ordering and retention of claimed packet contents;
- malformed oldest packet blocking newer claims; and
- shared-folder CLI deposit/list/claim metadata output.

Run this focused fixture suite before accepting changes to the snapshot contract.

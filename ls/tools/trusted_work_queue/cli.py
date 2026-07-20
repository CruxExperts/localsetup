"""Command-line entrypoints for trusted full-repository snapshots."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

try:
    from .shared_folder import (
        QueuePacket,
        SharedFolderError,
        claim_oldest_packet,
        deposit_packet,
        list_ready_packets,
    )
    from .snapshot import SnapshotError, create_snapshot, validate_snapshot
except ImportError:  # pragma: no cover - supports direct script execution.
    from shared_folder import (  # type: ignore
        QueuePacket,
        SharedFolderError,
        claim_oldest_packet,
        deposit_packet,
        list_ready_packets,
    )
    from snapshot import SnapshotError, create_snapshot, validate_snapshot  # type: ignore


def build_parser() -> argparse.ArgumentParser:
    """Build the small, model-agnostic snapshot command parser."""
    parser = argparse.ArgumentParser(
        prog="trusted-work-queue",
        description="Create or validate a complete trusted repository snapshot.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser(
        "snapshot-create",
        help="stream a complete repository tree to a gzip tar archive",
    )
    create.add_argument("source_dir", help="existing repository directory")
    create.add_argument("archive", help="destination archive path")

    validate = commands.add_parser(
        "snapshot-validate",
        help="validate an archive and its adjacent sidecar without extracting",
    )
    validate.add_argument("archive", help="archive path created by snapshot-create")

    deposit = commands.add_parser(
        "shared-deposit",
        help="stream a snapshot and opaque PRD into a local shared-folder queue",
    )
    deposit.add_argument("queue_root", help="shared-folder queue root")
    deposit.add_argument("archive", help="validated snapshot archive")
    deposit.add_argument("prd", help="opaque PRD bytes file")
    deposit.add_argument("--replication-count", type=int, required=True)

    shared_list = commands.add_parser(
        "shared-list",
        help="list verified ready packets in deterministic queue order",
    )
    shared_list.add_argument("queue_root", help="shared-folder queue root")

    claim = commands.add_parser(
        "shared-claim",
        help="claim the oldest ready packet without deleting its contents",
    )
    claim.add_argument("queue_root", help="shared-folder queue root")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a snapshot command and return a process exit status."""
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot-create":
            result = create_snapshot(args.source_dir, args.archive)
            _print_json(result.metadata.as_dict())
            return 0
        if args.command == "snapshot-validate":
            metadata = validate_snapshot(args.archive)
            _print_json({"valid": True, **metadata.as_dict()})
            return 0
        if args.command == "shared-deposit":
            packet = deposit_packet(
                args.queue_root,
                args.archive,
                args.prd,
                replication_count=args.replication_count,
            )
            _print_json(_packet_payload(packet))
            return 0
        if args.command == "shared-list":
            _print_json({"packets": [_packet_payload(packet) for packet in list_ready_packets(args.queue_root)]})
            return 0
        claim = claim_oldest_packet(args.queue_root)
        _print_json({"claimed": claim is not None, **(_packet_payload(claim.packet) if claim else {})})
        return 0
    except (SnapshotError, SharedFolderError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("error: filesystem operation failed", file=sys.stderr)
        return 1


def _packet_payload(packet: QueuePacket) -> dict[str, object]:
    """Render queue metadata without exposing local packet paths or PRD bytes."""
    return {
        "job_id": packet.job_id,
        "archive_sha256": packet.snapshot.archive_sha256,
        "archive_bytes": packet.snapshot.total_bytes,
        "prd_sha256": packet.prd_sha256,
        "prd_bytes": packet.prd_bytes,
        "replication_count": packet.replication_count,
        "enqueued_at": packet.enqueued_at,
    }


def _print_json(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout, ensure_ascii=True, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":  # pragma: no cover - exercised by the interpreter.
    raise SystemExit(main())

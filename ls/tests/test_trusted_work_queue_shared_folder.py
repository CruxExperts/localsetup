
"""Contract tests for immutable trusted queue shared-folder packets."""

from __future__ import annotations
import io

import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from unittest import mock
import unittest
from datetime import datetime, timezone
from pathlib import Path

_PACKAGE_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_PACKAGE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_TOOLS))

from trusted_work_queue.shared_folder import (  # noqa: E402
    CLAIMS_DIRECTORY,
    INCOMING_DIRECTORY,
    READY_FILENAME,
    SharedFolderError,
    claim_oldest_packet,
    deposit_packet,
    list_ready_packets,
    load_packet,
)
from trusted_work_queue.cli import main as cli_main  # noqa: E402
from trusted_work_queue.snapshot import create_snapshot  # noqa: E402
import trusted_work_queue.shared_folder as shared_folder_module  # noqa: E402


class SharedFolderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.queue_root = self.workspace / "queue"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_deposit_streams_exact_prd_and_publishes_verified_ready_packet(self) -> None:
        archive = self._snapshot("one", b"repository bytes")
        prd = self.workspace / "review.prd"
        prd_bytes = b"Review the complete repository.\x00Do not parse this payload.\n"
        prd.write_bytes(prd_bytes)

        packet = deposit_packet(
            self.queue_root,
            archive,
            prd,
            replication_count=3,
            enqueued_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(packet.prd_path.read_bytes(), prd_bytes)
        self.assertTrue(packet.ready_path.is_file())
        self.assertEqual(packet.replication_count, 3)
        self.assertEqual(load_packet(packet.packet_dir), packet)
        marker = json.loads(packet.ready_path.read_text(encoding="ascii"))
        self.assertNotIn("Review the complete repository", packet.ready_path.read_text(encoding="ascii"))
        self.assertEqual(marker["job_id"], packet.job_id)
        self.assertEqual(marker["prd_bytes"], len(prd_bytes))

    def test_cli_deposit_list_and_claim_expose_only_safe_metadata(self) -> None:
        archive = self._snapshot("cli", b"repository bytes")
        prd = self.workspace / "cli.prd"
        prd.write_bytes(b"opaque PRD instruction bytes")
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertEqual(
                cli_main(
                    [
                        "shared-deposit",
                        str(self.queue_root),
                        str(archive),
                        str(prd),
                        "--replication-count",
                        "1",
                    ]
                ),
                0,
            )
        deposited = json.loads(output.getvalue())
        self.assertNotIn("opaque PRD instruction bytes", output.getvalue())
        self.assertIn("job_id", deposited)

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["shared-list", str(self.queue_root)]), 0)
        self.assertEqual(len(json.loads(output.getvalue())["packets"]), 1)

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(cli_main(["shared-claim", str(self.queue_root)]), 0)
        self.assertTrue(json.loads(output.getvalue())["claimed"])

    def test_duplicate_snapshot_job_refuses_to_replace_existing_packet(self) -> None:
        archive = self._snapshot("one", b"repository bytes")
        prd = self.workspace / "review.prd"
        prd.write_bytes(b"same PRD")
        first = deposit_packet(self.queue_root, archive, prd, replication_count=1)
        before = first.ready_path.read_bytes()

        with self.assertRaises(SharedFolderError):
            deposit_packet(self.queue_root, archive, prd, replication_count=1)

        self.assertEqual(first.ready_path.read_bytes(), before)
        self.assertEqual(first.prd_path.read_bytes(), b"same PRD")

    def test_failed_staging_copy_leaves_no_packet_and_allows_retry(self) -> None:
        archive = self._snapshot("retry", b"repository bytes")
        prd = self.workspace / "retry.prd"
        prd.write_bytes(b"PRD")

        with mock.patch.object(
            shared_folder_module,
            "_copy_file",
            side_effect=SharedFolderError("simulated copy interruption"),
        ):
            with self.assertRaises(SharedFolderError):
                deposit_packet(self.queue_root, archive, prd, replication_count=1)

        incoming = self.queue_root / INCOMING_DIRECTORY
        self.assertEqual(list(incoming.iterdir()), [])
        packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)
        self.assertTrue(packet.ready_path.is_file())

    def test_concurrent_final_packet_publication_does_not_replace_existing_directory(self) -> None:
        archive = self._snapshot("race", b"repository bytes")
        prd = self.workspace / "race.prd"
        prd.write_bytes(b"PRD")
        original_rename = os.rename

        def publish_competing_packet(source: object, destination: object) -> None:
            final = Path(destination)
            final.mkdir()
            (final / "foreign-owner").write_bytes(b"do not replace")
            original_rename(source, destination)

        with mock.patch.object(
            shared_folder_module.os,
            "rename",
            side_effect=publish_competing_packet,
        ):
            with self.assertRaises(SharedFolderError):
                deposit_packet(self.queue_root, archive, prd, replication_count=1)

        packets = list((self.queue_root / INCOMING_DIRECTORY).iterdir())
        self.assertEqual(len(packets), 1)
        self.assertEqual((packets[0] / "foreign-owner").read_bytes(), b"do not replace")

    def test_staged_ready_marker_is_not_visible_to_list_or_claim(self) -> None:
        archive = self._snapshot("stage", b"repository bytes")
        prd = self.workspace / "stage.prd"
        prd.write_bytes(b"PRD")
        original_rename = os.rename

        def inspect_before_publish(source: object, destination: object) -> None:
            self.assertEqual(list_ready_packets(self.queue_root), [])
            self.assertIsNone(claim_oldest_packet(self.queue_root))
            original_rename(source, destination)

        with mock.patch.object(
            shared_folder_module.os,
            "rename",
            side_effect=inspect_before_publish,
        ):
            packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)

        self.assertTrue(packet.ready_path.is_file())

    def test_claimed_job_cannot_be_deposited_again(self) -> None:
        archive = self._snapshot("claimed", b"repository bytes")
        prd = self.workspace / "claimed.prd"
        prd.write_bytes(b"PRD")
        deposit_packet(self.queue_root, archive, prd, replication_count=1)
        self.assertIsNotNone(claim_oldest_packet(self.queue_root))

        with self.assertRaises(SharedFolderError):
            deposit_packet(self.queue_root, archive, prd, replication_count=1)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_queue_root_and_control_directory_symlinks_are_rejected(self) -> None:
        archive = self._snapshot("symlink", b"repository bytes")
        prd = self.workspace / "symlink.prd"
        prd.write_bytes(b"PRD")
        actual_root = self.workspace / "actual-queue"
        actual_root.mkdir()
        root_link = self.workspace / "queue-link"
        os.symlink(actual_root, root_link)

        with self.assertRaises(SharedFolderError):
            deposit_packet(root_link, archive, prd, replication_count=1)

        self.queue_root.mkdir()
        outside = self.workspace / "outside"
        outside.mkdir()
        os.symlink(outside, self.queue_root / INCOMING_DIRECTORY)
        with self.assertRaises(SharedFolderError):
            deposit_packet(self.queue_root, archive, prd, replication_count=1)

    def test_ready_packets_are_deterministically_ordered_and_claimed_without_deletion(self) -> None:
        first_archive = self._snapshot("first", b"first repository")
        second_archive = self._snapshot("second", b"second repository")
        first_prd = self.workspace / "first.prd"
        second_prd = self.workspace / "second.prd"
        first_prd.write_bytes(b"first")
        second_prd.write_bytes(b"second")
        later = deposit_packet(
            self.queue_root,
            second_archive,
            second_prd,
            replication_count=2,
            enqueued_at=datetime(2026, 7, 20, 0, 0, 2, tzinfo=timezone.utc),
        )
        earlier = deposit_packet(
            self.queue_root,
            first_archive,
            first_prd,
            replication_count=2,
            enqueued_at=datetime(2026, 7, 20, 0, 0, 1, tzinfo=timezone.utc),
        )

        self.assertEqual([packet.job_id for packet in list_ready_packets(self.queue_root)], [earlier.job_id, later.job_id])
        claim = claim_oldest_packet(self.queue_root)

        assert claim is not None
        self.assertEqual(claim.packet.job_id, earlier.job_id)
        self.assertTrue(claim.claim_marker.is_file())
        self.assertTrue((self.queue_root / CLAIMS_DIRECTORY / earlier.job_id / READY_FILENAME).is_file())
        self.assertFalse((self.queue_root / INCOMING_DIRECTORY / earlier.job_id).exists())
        self.assertEqual([packet.job_id for packet in list_ready_packets(self.queue_root)], [later.job_id])

    def test_invalid_ready_packet_blocks_claim_instead_of_skipping_to_newer_packet(self) -> None:
        first_archive = self._snapshot("first", b"first repository")
        second_archive = self._snapshot("second", b"second repository")
        first_prd = self.workspace / "first.prd"
        second_prd = self.workspace / "second.prd"
        first_prd.write_bytes(b"first")
        second_prd.write_bytes(b"second")
        first = deposit_packet(
            self.queue_root,
            first_archive,
            first_prd,
            replication_count=1,
            enqueued_at=datetime(2026, 7, 20, 0, 0, 1, tzinfo=timezone.utc),
        )
        second = deposit_packet(
            self.queue_root,
            second_archive,
            second_prd,
            replication_count=1,
            enqueued_at=datetime(2026, 7, 20, 0, 0, 2, tzinfo=timezone.utc),
        )
        first.prd_path.write_bytes(b"tampered")

        with self.assertRaises(SharedFolderError):
            claim_oldest_packet(self.queue_root)

        self.assertTrue((self.queue_root / INCOMING_DIRECTORY / first.job_id).is_dir())
        self.assertTrue((self.queue_root / INCOMING_DIRECTORY / second.job_id).is_dir())
        self.assertFalse((self.queue_root / CLAIMS_DIRECTORY / second.job_id).exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_prd_symlink_is_rejected(self) -> None:
        archive = self._snapshot("one", b"repository bytes")
        target = self.workspace / "target.prd"
        target.write_bytes(b"PRD")
        prd = self.workspace / "review.prd"
        os.symlink(target, prd)

        with self.assertRaises(SharedFolderError):
            deposit_packet(self.queue_root, archive, prd, replication_count=1)

    def _snapshot(self, name: str, content: bytes) -> Path:
        source = self.workspace / name
        source.mkdir()
        (source / ".git").mkdir()
        (source / ".git" / "HEAD").write_text(
            "0123456789abcdef0123456789abcdef01234567\n", encoding="ascii"
        )
        (source / "payload.bin").write_bytes(content)
        archive = self.workspace / f"{name}.tar.gz"
        create_snapshot(source, archive)
        return archive


if __name__ == "__main__":
    unittest.main()

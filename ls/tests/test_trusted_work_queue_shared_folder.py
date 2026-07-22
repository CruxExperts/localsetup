
"""Contract tests for immutable trusted queue shared-folder packets."""

from __future__ import annotations
import io

import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
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
    PRD_FILENAME,
    SNAPSHOT_FILENAME,
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

    def test_packet_members_are_mode_0600_before_write_across_umasks(self) -> None:
        archive = self._snapshot("modes", b"repository bytes")
        prd = self.workspace / "modes.prd"
        prd.write_bytes(b"PRD")
        original_open = os.open
        original_fchmod = os.fchmod
        created_descriptors: dict[int, tuple[str, int]] = {}
        observed_modes: dict[str, tuple[int, int, int]] = {}

        def observe_create(path: object, flags: int, mode: int = 0o777, *args: object, **kwargs: object) -> int:
            descriptor = original_open(path, flags, mode, *args, **kwargs)
            if flags & os.O_CREAT and flags & os.O_EXCL:
                created_descriptors[descriptor] = (Path(path).name, mode)
            return descriptor

        def observe_fchmod(descriptor: int, mode: int, *args: object, **kwargs: object) -> None:
            original_fchmod(descriptor, mode, *args, **kwargs)
            if descriptor in created_descriptors:
                name, requested_mode = created_descriptors[descriptor]
                observed_modes[name] = (
                    requested_mode,
                    mode,
                    os.fstat(descriptor).st_mode & 0o777,
                )

        previous_umask = os.umask(0)
        try:
            with (
                mock.patch.object(shared_folder_module.os, "open", side_effect=observe_create),
                mock.patch.object(shared_folder_module.os, "fchmod", side_effect=observe_fchmod),
            ):
                permissive_packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)
        finally:
            os.umask(previous_umask)

        previous_umask = os.umask(0o777)
        try:
            with (
                mock.patch.object(shared_folder_module.os, "open", side_effect=observe_create),
                mock.patch.object(shared_folder_module.os, "fchmod", side_effect=observe_fchmod),
            ):
                shared_folder_module._copy_file(
                    archive,
                    self.workspace / "restrictive-member.bin",
                )
        finally:
            os.umask(previous_umask)

        for name in (SNAPSHOT_FILENAME, f"{SNAPSHOT_FILENAME}.manifest.json", PRD_FILENAME):
            self.assertEqual(observed_modes.get(name), (0o600, 0o600, 0o600), name)
        self.assertEqual(observed_modes["restrictive-member.bin"], (0o600, 0o600, 0o600))
        for member in permissive_packet.packet_dir.iterdir():
            if member.is_file():
                self.assertEqual(member.stat().st_mode & 0o777, 0o600, member.name)

    def test_ready_marker_accepts_bounded_json_and_rejects_valid_oversize(self) -> None:
        archive = self._snapshot("bounded", b"repository bytes")
        prd = self.workspace / "bounded.prd"
        prd.write_bytes(b"PRD")
        packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)
        marker = packet.ready_path.read_bytes().rstrip(b"\n")
        limit = shared_folder_module._READY_MARKER_MAX_BYTES
        self.assertLess(len(marker), limit)

        packet.ready_path.write_bytes(marker + b" " * (limit - len(marker)))
        self.assertEqual(load_packet(packet.packet_dir), packet)

        packet.ready_path.write_bytes(marker + b" " * (limit - len(marker) + 1))
        with self.assertRaises(SharedFolderError):
            load_packet(packet.packet_dir)

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "symlink"), "special files are unavailable")
    def test_ready_marker_fifo_nonregular_and_symlink_reject_promptly(self) -> None:
        archive = self._snapshot("marker-types", b"repository bytes")
        prd = self.workspace / "marker-types.prd"
        prd.write_bytes(b"PRD")
        packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)
        ready = packet.ready_path
        target = self.workspace / "marker-target"
        target.write_bytes(b"not a marker")

        for marker_type in ("fifo", "directory", "symlink"):
            if ready.is_dir() and not ready.is_symlink():
                ready.rmdir()
            elif ready.exists() or ready.is_symlink():
                ready.unlink()
            if marker_type == "fifo":
                os.mkfifo(ready)
            elif marker_type == "directory":
                ready.mkdir()
            else:
                os.symlink(target, ready)

            with self.assertRaises(SharedFolderError):
                load_packet(packet.packet_dir)

    def test_ready_marker_descriptor_closes_when_read_fails(self) -> None:
        marker = self.workspace / READY_FILENAME
        marker.write_bytes(b"{}")
        with (
            mock.patch.object(shared_folder_module.os, "read", side_effect=OSError("read failed")),
            mock.patch.object(shared_folder_module.os, "close", wraps=os.close) as close,
        ):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._read_ready_marker(marker)
        close.assert_called_once()

    @unittest.skipUnless(hasattr(sys, "set_int_max_str_digits"), "integer conversion limits are unavailable")
    def test_ready_marker_pathological_integer_is_normalized(self) -> None:
        marker = self.workspace / READY_FILENAME
        marker.write_bytes(b'{"integer":' + b"1" * 700 + b"}")
        previous_limit = sys.get_int_max_str_digits()
        sys.set_int_max_str_digits(640)
        try:
            with self.assertRaises(SharedFolderError):
                shared_folder_module._read_ready_marker(marker)
        finally:
            sys.set_int_max_str_digits(previous_limit)

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

    def test_cli_rejects_removed_shared_materialize_command(self) -> None:
        errors = io.StringIO()

        with redirect_stderr(errors):
            with self.assertRaises(SystemExit) as raised:
                cli_main(["shared-materialize", str(self.queue_root), str(self.workspace / "candidates")])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("invalid choice", errors.getvalue())
        self.assertIn("shared-materialize", errors.getvalue())

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

    def test_concurrent_empty_final_packet_directory_is_not_replaced(self) -> None:
        archive = self._snapshot("race", b"repository bytes")
        prd = self.workspace / "race.prd"
        prd.write_bytes(b"PRD")
        incoming = self.queue_root / INCOMING_DIRECTORY
        original_publish = shared_folder_module._rename_directory_no_clobber

        def publish_competing_packet(source: Path, destination: Path) -> None:
            destination.mkdir()
            original_publish(source, destination)

        with mock.patch.object(
            shared_folder_module,
            "_rename_directory_no_clobber",
            side_effect=publish_competing_packet,
        ):
            with self.assertRaises(SharedFolderError):
                deposit_packet(self.queue_root, archive, prd, replication_count=1)

        packets = list(incoming.iterdir())
        self.assertEqual(len(packets), 1)
        self.assertEqual(list(packets[0].iterdir()), [])

    def test_macos_packet_publication_uses_exclusive_native_rename(self) -> None:
        renamex_np = mock.Mock(return_value=0)
        native_library = mock.Mock(renamex_np=renamex_np)
        source = self.workspace / "source"
        destination = self.workspace / "destination"

        with (
            mock.patch.object(shared_folder_module.sys, "platform", "darwin"),
            mock.patch.object(shared_folder_module, "_NATIVE_LIBRARY", native_library),
        ):
            shared_folder_module._rename_directory_no_clobber(source, destination)

        renamex_np.assert_called_once_with(
            os.fsencode(source),
            os.fsencode(destination),
            0x00000004,
        )

    def test_staged_ready_marker_is_not_visible_before_publication(self) -> None:
        archive = self._snapshot("stage", b"repository bytes")
        prd = self.workspace / "stage.prd"
        prd.write_bytes(b"PRD")
        original_publish = shared_folder_module._rename_directory_no_clobber

        def inspect_before_publish(source: Path, destination: Path) -> None:
            self.assertEqual(list_ready_packets(self.queue_root), [])
            self.assertIsNone(claim_oldest_packet(self.queue_root))
            original_publish(source, destination)

        with mock.patch.object(
            shared_folder_module,
            "_rename_directory_no_clobber",
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

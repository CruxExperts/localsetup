
"""Contract tests for immutable trusted queue shared-folder packets."""

from __future__ import annotations
import io
import json
import os
import signal
import stat
import sys
import tempfile
import threading
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
    QUEUE_LOCK_FILENAME,
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
            original_publish(source, destination)

        with mock.patch.object(
            shared_folder_module,
            "_rename_directory_no_clobber",
            side_effect=inspect_before_publish,
        ):
            packet = deposit_packet(self.queue_root, archive, prd, replication_count=1)

        self.assertTrue(packet.ready_path.is_file())

    def test_same_job_deposit_and_claim_are_serialized_at_final_publication(self) -> None:
        archive = self._snapshot("serialized", b"repository bytes")
        prd_a = self.workspace / "serialized-a.prd"
        prd_b = self.workspace / "serialized-b.prd"
        prd_a.write_bytes(b"depositor-a")
        prd_b.write_bytes(b"depositor-b")

        b_entered_publication = threading.Event()
        release_b_publication = threading.Event()
        a_lock_attempted = threading.Event()
        claim_lock_attempted = threading.Event()
        a_finished = threading.Event()
        claim_finished = threading.Event()
        deposits: list[object] = []
        deposit_errors: list[BaseException] = []
        claims: list[object] = []
        original_publish = shared_folder_module._rename_directory_no_clobber
        original_flock = shared_folder_module.fcntl.flock

        def pause_b_publication(source: Path, destination: Path) -> None:
            if threading.current_thread().name == "depositor-b":
                b_entered_publication.set()
                if not release_b_publication.wait(5):
                    raise RuntimeError("publication release was not signaled")
            original_publish(source, destination)

        def observe_flock(descriptor: int, operation: int) -> None:
            if operation == shared_folder_module.fcntl.LOCK_EX:
                if threading.current_thread().name == "depositor-a":
                    a_lock_attempted.set()
                elif threading.current_thread().name == "claimant":
                    claim_lock_attempted.set()
            original_flock(descriptor, operation)

        def deposit(prd: Path, *, finished: threading.Event | None = None) -> None:
            try:
                deposits.append(deposit_packet(self.queue_root, archive, prd, replication_count=1))
            except BaseException as exc:  # pragma: no cover - asserted below
                deposit_errors.append(exc)
            finally:
                if finished is not None:
                    finished.set()

        def claim() -> None:
            try:
                claims.append(claim_oldest_packet(self.queue_root))
            finally:
                claim_finished.set()

        with (
            mock.patch.object(
                shared_folder_module,
                "_rename_directory_no_clobber",
                side_effect=pause_b_publication,
            ),
            mock.patch.object(shared_folder_module.fcntl, "flock", side_effect=observe_flock),
        ):
            depositor_b = threading.Thread(
                target=deposit,
                args=(prd_b,),
                name="depositor-b",
            )
            depositor_b.start()
            self.assertTrue(b_entered_publication.wait(5))

            depositor_a = threading.Thread(
                target=deposit,
                args=(prd_a,),
                kwargs={"finished": a_finished},
                name="depositor-a",
            )
            depositor_a.start()
            self.assertTrue(a_lock_attempted.wait(5))
            self.assertFalse(a_finished.is_set())

            claimant = threading.Thread(target=claim, name="claimant")
            claimant.start()
            self.assertTrue(claim_lock_attempted.wait(5))
            self.assertFalse(claim_finished.is_set())
            release_b_publication.set()
            depositor_b.join(5)
            depositor_a.join(5)
            claimant.join(5)

        self.assertFalse(depositor_b.is_alive())
        self.assertFalse(depositor_a.is_alive())
        self.assertFalse(claimant.is_alive())
        self.assertEqual(len(deposits), 1)
        self.assertEqual(len(deposit_errors), 1)
        self.assertIsInstance(deposit_errors[0], SharedFolderError)
        self.assertEqual(len(claims), 1)
        claimed = claims[0]
        self.assertIsNotNone(claimed)
        job_id = deposits[0].job_id  # type: ignore[union-attr]
        self.assertEqual(claimed.packet.job_id, job_id)  # type: ignore[union-attr]
        self.assertFalse((self.queue_root / INCOMING_DIRECTORY / job_id).exists())
        self.assertTrue((self.queue_root / CLAIMS_DIRECTORY / job_id).is_dir())
        self.assertTrue((self.queue_root / CLAIMS_DIRECTORY / f"{job_id}.claim").is_file())
        self.assertEqual(list_ready_packets(self.queue_root), [])

    def test_queue_operation_lock_is_owner_only_regular_file_and_rejects_fifo(self) -> None:
        archive = self._snapshot("lock-mode", b"repository bytes")
        prd = self.workspace / "lock-mode.prd"
        prd.write_bytes(b"PRD")
        deposit_packet(self.queue_root, archive, prd, replication_count=1)
        lock_path = self.queue_root / QUEUE_LOCK_FILENAME
        self.assertTrue(stat.S_ISREG(lock_path.stat().st_mode))
        self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)

        lock_path.unlink()
        os.mkfifo(lock_path)
        with self.assertRaises(SharedFolderError):
            with shared_folder_module._queue_operation_lock(self.queue_root):
                pass

    def test_queue_operation_lock_open_flock_and_close_failures_are_typed(self) -> None:
        shared_folder_module._prepare_queue_root(self.queue_root)
        lock_path = self.queue_root / QUEUE_LOCK_FILENAME

        with mock.patch.object(shared_folder_module.os, "open", side_effect=OSError("open failed")):
            with self.assertRaises(SharedFolderError):
                with shared_folder_module._queue_operation_lock(self.queue_root):
                    pass

        with mock.patch.object(
            shared_folder_module.fcntl,
            "flock",
            side_effect=OSError("flock failed"),
        ):
            with self.assertRaises(SharedFolderError):
                with shared_folder_module._queue_operation_lock(self.queue_root):
                    pass

        real_close = shared_folder_module.os.close

        def fail_close(descriptor: int) -> None:
            real_close(descriptor)
            raise OSError("close failed")

        with mock.patch.object(shared_folder_module.os, "close", side_effect=fail_close):
            with self.assertRaises(SharedFolderError):
                with shared_folder_module._queue_operation_lock(self.queue_root):
                    pass
        self.assertTrue(lock_path.is_file())

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

    @unittest.skipUnless(hasattr(os, "mkfifo") and hasattr(os, "symlink"), "special files are unavailable")
    def test_hash_rejects_fifo_nonregular_and_symlink_promptly(self) -> None:
        fifo = self.workspace / "member.fifo"
        os.mkfifo(fifo)
        timeout = signal.getsignal(signal.SIGALRM)

        def interrupt_fifo(_signum: int, _frame: object) -> None:
            raise AssertionError("FIFO hash did not reject promptly")

        signal.signal(signal.SIGALRM, interrupt_fifo)
        signal.setitimer(signal.ITIMER_REAL, 1)
        try:
            with self.assertRaises(SharedFolderError):
                shared_folder_module._hash_file(fifo)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, timeout)

        directory = self.workspace / "member-directory"
        directory.mkdir()
        with self.assertRaises(SharedFolderError):
            shared_folder_module._hash_file(directory)

        target = self.workspace / "member-target"
        target.write_bytes(b"target")
        symlink = self.workspace / "member-symlink"
        os.symlink(target, symlink)
        with self.assertRaises(SharedFolderError):
            shared_folder_module._hash_file(symlink)

    def test_hash_opens_bound_member_with_safe_flags(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        original_open = os.open
        observed_flags: list[int] = []

        def observe_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if Path(path) == source:
                observed_flags.append(flags)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(shared_folder_module.os, "open", side_effect=observe_open):
            digest, total = shared_folder_module._hash_file(source)

        self.assertEqual((digest, total), (shared_folder_module.hashlib.sha256(b"source").hexdigest(), 6))
        self.assertEqual(len(observed_flags), 1)
        flags = observed_flags[0]
        self.assertEqual(flags & os.O_ACCMODE, os.O_RDONLY)
        self.assertTrue(flags & os.O_NOFOLLOW)
        self.assertTrue(flags & os.O_NONBLOCK)
        if hasattr(os, "O_CLOEXEC"):
            self.assertTrue(flags & os.O_CLOEXEC)

    def test_hash_rejects_source_path_swap_after_read(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        replacement = self.workspace / "replacement.bin"
        replacement.write_bytes(b"replacement")
        original_read = os.read
        swapped = False

        def read_and_swap(descriptor: int, size: int) -> bytes:
            nonlocal swapped
            chunk = original_read(descriptor, size)
            if not swapped:
                source.rename(self.workspace / "original-source.bin")
                replacement.rename(source)
                swapped = True
            return chunk

        with mock.patch.object(shared_folder_module.os, "read", side_effect=read_and_swap):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._hash_file(source)
        self.assertTrue(swapped)

    def test_hash_rejects_source_size_mutation_after_read(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        original_read = os.read
        mutated = False

        def read_and_mutate(descriptor: int, size: int) -> bytes:
            nonlocal mutated
            chunk = original_read(descriptor, size)
            if not mutated:
                os.truncate(source, 1)
                mutated = True
            return chunk

        with mock.patch.object(shared_folder_module.os, "read", side_effect=read_and_mutate):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._hash_file(source)
        self.assertTrue(mutated)

    def test_hash_closes_descriptor_when_read_fails(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        original_open = os.open
        original_close = os.close
        opened: list[int] = []
        closed: list[int] = []

        def observe_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            descriptor = original_open(path, flags, *args, **kwargs)
            if Path(path) == source:
                opened.append(descriptor)
            return descriptor

        def observe_close(descriptor: int) -> None:
            closed.append(descriptor)
            original_close(descriptor)

        with (
            mock.patch.object(shared_folder_module.os, "open", side_effect=observe_open),
            mock.patch.object(shared_folder_module.os, "close", side_effect=observe_close),
            mock.patch.object(shared_folder_module.os, "read", side_effect=OSError("read failed")),
        ):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._hash_file(source)

        self.assertEqual(opened, closed)

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_copy_source_symlink_is_rejected_before_destination_creation(self) -> None:
        target = self.workspace / "target.bin"
        target.write_bytes(b"source")
        source = self.workspace / "source.bin"
        os.symlink(target, source)
        destination = self.workspace / "destination.bin"

        with self.assertRaises(SharedFolderError):
            shared_folder_module._copy_file(source, destination)

        self.assertFalse(destination.exists())

    def test_copy_nonregular_source_is_rejected_before_open(self) -> None:
        source = self.workspace / "source-directory"
        source.mkdir()
        destination = self.workspace / "destination.bin"

        with self.assertRaises(SharedFolderError):
            shared_folder_module._copy_file(source, destination)

        self.assertFalse(destination.exists())

    def test_copy_source_open_requires_no_follow_nonblocking_and_close_on_exec(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        destination = self.workspace / "destination.bin"
        original_open = os.open
        observed_source_flags: list[int] = []

        def observe_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            if Path(path) == source:
                observed_source_flags.append(flags)
            return original_open(path, flags, *args, **kwargs)

        with mock.patch.object(shared_folder_module.os, "open", side_effect=observe_open):
            shared_folder_module._copy_file(source, destination)

        self.assertEqual(len(observed_source_flags), 1)
        source_flags = observed_source_flags[0]
        self.assertEqual(source_flags & os.O_ACCMODE, os.O_RDONLY)
        self.assertTrue(source_flags & os.O_NOFOLLOW)
        self.assertTrue(source_flags & os.O_NONBLOCK)
        if hasattr(os, "O_CLOEXEC"):
            self.assertTrue(source_flags & os.O_CLOEXEC)

    def test_copy_rejects_source_path_swap_after_streaming(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        replacement = self.workspace / "replacement.bin"
        replacement.write_bytes(b"replacement")
        destination = self.workspace / "destination.bin"
        original_read = os.read
        swapped = False

        def read_and_swap(descriptor: int, size: int) -> bytes:
            nonlocal swapped
            chunk = original_read(descriptor, size)
            if not swapped:
                source.rename(self.workspace / "original-source.bin")
                replacement.rename(source)
                swapped = True
            return chunk

        with mock.patch.object(shared_folder_module.os, "read", side_effect=read_and_swap):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._copy_file(source, destination)

        self.assertTrue(swapped)

    def test_copy_rejects_source_size_mutation_after_streaming(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        destination = self.workspace / "destination.bin"
        original_read = os.read
        mutated = False

        def read_and_mutate(descriptor: int, size: int) -> bytes:
            nonlocal mutated
            chunk = original_read(descriptor, size)
            if not mutated:
                os.truncate(source, 1)
                mutated = True
            return chunk

        with mock.patch.object(shared_folder_module.os, "read", side_effect=read_and_mutate):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._copy_file(source, destination)

        self.assertTrue(mutated)

    def test_copy_closes_source_and_destination_descriptors_on_stream_failure(self) -> None:
        source = self.workspace / "source.bin"
        source.write_bytes(b"source")
        destination = self.workspace / "destination.bin"
        original_open = os.open
        original_close = os.close
        opened: set[int] = set()
        closed: set[int] = set()

        def observe_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            descriptor = original_open(path, flags, *args, **kwargs)
            if Path(path) in (source, destination):
                opened.add(descriptor)
            return descriptor

        def observe_close(descriptor: int) -> None:
            closed.add(descriptor)
            original_close(descriptor)

        def fail_read(descriptor: int, size: int) -> bytes:
            raise OSError("injected read failure")

        with (
            mock.patch.object(shared_folder_module.os, "open", side_effect=observe_open),
            mock.patch.object(shared_folder_module.os, "close", side_effect=observe_close),
            mock.patch.object(shared_folder_module.os, "read", side_effect=fail_read),
        ):
            with self.assertRaises(SharedFolderError):
                shared_folder_module._copy_file(source, destination)

        self.assertEqual(opened, closed)

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

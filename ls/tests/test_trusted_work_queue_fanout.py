"""Contract tests for detached offline candidate fanout."""

from __future__ import annotations

import io
import json
import os
import stat
import sys
import tarfile
from unittest import mock
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

_PACKAGE_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_PACKAGE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_TOOLS))

from trusted_work_queue.cli import main as cli_main  # noqa: E402
from trusted_work_queue.fanout import FANOUT_FILENAME, FanoutError, materialize_claim, materialize_oldest_claim  # noqa: E402
from trusted_work_queue.shared_folder import claim_oldest_packet, deposit_packet  # noqa: E402
from trusted_work_queue.snapshot import SnapshotMetadata, create_snapshot  # noqa: E402
import trusted_work_queue.fanout as fanout_module  # noqa: E402


class CandidateFanoutContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.queue_root = self.workspace / "queue"
        self.candidate_root = self.workspace / "candidates"

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_materialize_claim_publishes_exact_isolated_replicas_and_manifest(self) -> None:
        claim, prd_bytes = self._claim(replication_count=2)

        fanout = materialize_claim(claim, self.candidate_root)

        self.assertEqual([candidate.candidate_id for candidate in fanout.candidates], ["candidate-001", "candidate-002"])
        self.assertTrue(claim.packet.packet_dir.exists())
        self.assertTrue(claim.claim_marker.is_file())
        self.assertTrue(fanout.manifest_path.is_file())
        payload = json.loads(fanout.manifest_path.read_text(encoding="ascii"))
        self.assertTrue(payload["claim_retained"])
        self.assertEqual(payload["job_id"], claim.packet.job_id)
        self.assertEqual(payload["archive_sha256"], claim.packet.snapshot.archive_sha256)
        self.assertNotIn("opaque review instructions", fanout.manifest_path.read_text(encoding="ascii"))

        first, second = fanout.candidates
        self.assertEqual((first.source_dir / "tracked.txt").read_bytes(), b"repository bytes")
        self.assertEqual((second.source_dir / ".git" / "HEAD").read_text(encoding="ascii"), "ref: refs/heads/main\n")
        self.assertEqual(first.prd_path.read_bytes(), prd_bytes)
        self.assertEqual(second.prd_path.read_bytes(), prd_bytes)
        (first.source_dir / "tracked.txt").write_bytes(b"candidate one only")
        self.assertEqual((second.source_dir / "tracked.txt").read_bytes(), b"repository bytes")


    def test_tampered_claimed_prd_refuses_fanout_and_keeps_claim(self) -> None:
        claim, _ = self._claim(replication_count=1)
        claim.packet.prd_path.write_bytes(b"tampered")

        with self.assertRaises(FanoutError):
            materialize_claim(claim, self.candidate_root)

        self.assertTrue(claim.packet.packet_dir.exists())
        self.assertTrue(claim.claim_marker.exists())
        self.assertFalse((self.candidate_root / claim.packet.job_id).exists())

    def test_existing_job_output_is_never_replaced(self) -> None:
        claim, _ = self._claim(replication_count=1)
        self.candidate_root.mkdir(mode=0o700)
        existing = self.candidate_root / claim.packet.job_id
        existing.mkdir()
        (existing / "foreign-owner").write_bytes(b"preserve")

        with self.assertRaises(FanoutError):
            materialize_claim(claim, self.candidate_root)

        self.assertEqual((existing / "foreign-owner").read_bytes(), b"preserve")
        self.assertTrue(claim.packet.packet_dir.exists())

    def test_empty_existing_job_output_is_never_replaced(self) -> None:
        claim, _ = self._claim(replication_count=1)
        self.candidate_root.mkdir(mode=0o700)
        existing = self.candidate_root / claim.packet.job_id
        existing.mkdir()

        with self.assertRaises(FanoutError):
            materialize_claim(claim, self.candidate_root)

        self.assertTrue(existing.is_dir())
        self.assertEqual(list(existing.iterdir()), [])
        self.assertTrue(claim.packet.packet_dir.exists())

    def test_concurrent_empty_job_reservation_blocks_publish(self) -> None:
        claim, _ = self._claim(replication_count=1)
        original_reserve = fanout_module._reserve_job_dir

        def reserve_empty_output(path: Path) -> None:
            self.candidate_root.mkdir(mode=0o700, exist_ok=True)
            path.mkdir()
            original_reserve(path)

        with mock.patch.object(fanout_module, "_reserve_job_dir", side_effect=reserve_empty_output):
            with self.assertRaises(FanoutError):
                materialize_claim(claim, self.candidate_root)

        existing = self.candidate_root / claim.packet.job_id
        self.assertTrue(existing.is_dir())
        self.assertEqual(list(existing.iterdir()), [])
        self.assertTrue(claim.packet.packet_dir.exists())


    def test_candidate_root_parent_rejects_group_writable_directory(self) -> None:
        claim, _ = self._claim(replication_count=1)
        unsafe_parent = self.workspace / "unsafe-parent"
        unsafe_parent.mkdir(mode=0o700)
        os.chmod(unsafe_parent, 0o720)
        candidate_root = unsafe_parent / "candidates"

        with self.assertRaises(FanoutError):
            materialize_claim(claim, candidate_root)
        self.assertFalse(candidate_root.exists())

    def test_candidate_root_final_symbolic_link_is_rejected(self) -> None:
        claim, _ = self._claim(replication_count=1)
        real_parent = self.workspace / "real-parent"
        real_parent.mkdir(mode=0o700)
        linked_target = self.workspace / "linked-target"
        linked_target.mkdir(mode=0o700)
        candidate_root = real_parent / "candidates"
        candidate_root.symlink_to(linked_target, target_is_directory=True)

        with self.assertRaises(FanoutError):
            materialize_claim(claim, candidate_root)
        self.assertTrue(candidate_root.is_symlink())
    def test_intermediate_symlink_retarget_stays_on_canonical_parent(self) -> None:
        claim, _ = self._claim(replication_count=1)
        first_parent = self.workspace / "first-parent"
        second_parent = self.workspace / "second-parent"
        first_parent.mkdir(mode=0o700)
        second_parent.mkdir(mode=0o700)
        input_parent = self.workspace / "input-parent"
        input_parent.symlink_to(first_parent, target_is_directory=True)
        candidate_root = input_parent / "candidates"
        original_stage = fanout_module._stage_snapshot

        def stage_then_retarget(packet: object, stage_dir: Path) -> Path:
            staged = original_stage(packet, stage_dir)
            input_parent.unlink()
            input_parent.symlink_to(second_parent, target_is_directory=True)
            return staged

        with mock.patch.object(fanout_module, "_stage_snapshot", side_effect=stage_then_retarget):
            fanout = materialize_claim(claim, candidate_root)

        expected_job = first_parent / "candidates" / claim.packet.job_id
        self.assertEqual(fanout.job_dir, expected_job)
        self.assertTrue((expected_job / FANOUT_FILENAME).is_file())
        self.assertFalse((second_parent / "candidates" / claim.packet.job_id).exists())

    def test_nested_root_creation_syncs_each_new_parent_entry(self) -> None:
        claim, _ = self._claim(replication_count=1)
        candidate_root = self.workspace / "nested-parent" / "inner" / "candidates"
        original_fsync = fanout_module._fsync_directory
        synced: list[Path] = []

        def observe_sync(path: Path) -> None:
            synced.append(path)
            original_fsync(path)

        with mock.patch.object(fanout_module, "_fsync_directory", side_effect=observe_sync):
            materialize_claim(claim, candidate_root)

        self.assertIn(self.workspace, synced)
        self.assertIn(self.workspace / "nested-parent", synced)
        self.assertIn(self.workspace / "nested-parent" / "inner", synced)


    def test_nested_root_creation_forces_owner_modes_under_restrictive_umask(self) -> None:
        claim, _ = self._claim(replication_count=1)
        candidate_root = self.workspace / "umask-parent" / "inner" / "candidates"
        old_umask = os.umask(0o777)
        try:
            fanout = materialize_claim(claim, candidate_root)
        finally:
            os.umask(old_umask)

        self.assertTrue(fanout.manifest_path.is_file())
        for path in (
            self.workspace / "umask-parent",
            self.workspace / "umask-parent" / "inner",
            candidate_root,
        ):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)

    def test_staged_archive_binds_all_replicas_before_source_replacement(self) -> None:
        claim, _ = self._claim(replication_count=2)
        original_stage = fanout_module._stage_snapshot

        def stage_then_replace_source(packet: object, stage_dir: Path) -> Path:
            staged = original_stage(packet, stage_dir)
            claim.packet.archive_path.write_bytes(b"replaced after staging")
            return staged

        with mock.patch.object(fanout_module, "_stage_snapshot", side_effect=stage_then_replace_source):
            fanout = materialize_claim(claim, self.candidate_root)

        for candidate in fanout.candidates:
            self.assertEqual((candidate.source_dir / "tracked.txt").read_bytes(), b"repository bytes")

    def test_held_staged_descriptor_survives_staged_path_replacement(self) -> None:
        claim, _ = self._claim(replication_count=1)
        original_open = fanout_module._open_staged_snapshot
        replacement = self.workspace / "replacement.tar"
        with tarfile.open(replacement, mode="w") as tar:
            root = tarfile.TarInfo("repository")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            member = tarfile.TarInfo("repository/replaced.txt")
            member.size = len(b"replacement")
            tar.addfile(member, io.BytesIO(b"replacement"))
        replacement_bytes = replacement.read_bytes()

        def open_then_replace(path: Path, expected: object) -> object:
            handle = original_open(path, expected)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            path.write_bytes(replacement_bytes)
            return handle

        with mock.patch.object(fanout_module, "_open_staged_snapshot", side_effect=open_then_replace):
            fanout = materialize_claim(claim, self.candidate_root)

        source = fanout.candidates[0].source_dir
        self.assertEqual((source / "tracked.txt").read_bytes(), b"repository bytes")
        self.assertFalse((source / "replaced.txt").exists())

    def test_same_uid_descriptor_mutation_after_extraction_blocks_manifest(self) -> None:
        claim, _ = self._claim(replication_count=1)
        original_open = fanout_module._open_staged_snapshot
        original_materialize = fanout_module._materialize_candidate
        mutator_fd: dict[str, int] = {}

        def open_with_mutator(path: Path, expected: object) -> object:
            descriptor = os.open(path, os.O_RDWR)
            try:
                handle = original_open(path, expected)
            except BaseException:
                os.close(descriptor)
                raise
            mutator_fd["value"] = descriptor
            return handle

        def materialize_then_mutate(
            packet: object,
            job_dir: Path,
            staged_archive: object,
            index: int,
        ) -> object:
            result = original_materialize(packet, job_dir, staged_archive, index)
            os.ftruncate(mutator_fd["value"], 0)
            return result

        try:
            with (
                mock.patch.object(fanout_module, "_open_staged_snapshot", side_effect=open_with_mutator),
                mock.patch.object(fanout_module, "_materialize_candidate", side_effect=materialize_then_mutate),
            ):
                with self.assertRaises(FanoutError):
                    materialize_claim(claim, self.candidate_root)
        finally:
            descriptor = mutator_fd.pop("value", None)
            if descriptor is not None:
                os.close(descriptor)

        job_dir = self.candidate_root / claim.packet.job_id
        self.assertTrue(job_dir.is_dir())
        self.assertFalse((job_dir / FANOUT_FILENAME).exists())

    def test_archive_replacement_before_staging_is_rejected_by_retained_bytes(self) -> None:
        claim, _ = self._claim(replication_count=1)
        original_stage = fanout_module._stage_snapshot

        def replace_before_stage(packet: object, stage_dir: Path) -> Path:
            claim.packet.archive_path.write_bytes(b"replaced before staging")
            return original_stage(packet, stage_dir)

        with mock.patch.object(fanout_module, "_stage_snapshot", side_effect=replace_before_stage):
            with self.assertRaises(FanoutError):
                materialize_claim(claim, self.candidate_root)

        self.assertFalse((self.candidate_root / claim.packet.job_id).exists())

    def test_source_archive_symbolic_link_is_rejected(self) -> None:
        claim, _ = self._claim(replication_count=1)
        archive = claim.packet.archive_path
        replacement = self.workspace / "replacement.tar.gz"
        replacement.write_bytes(archive.read_bytes())
        archive.unlink()
        archive.symlink_to(replacement)

        with self.assertRaises(FanoutError):
            materialize_claim(claim, self.candidate_root)
        self.assertFalse((self.candidate_root / claim.packet.job_id).exists())

    def test_read_only_archive_directories_are_durable_after_extraction(self) -> None:
        archive = self.workspace / "readonly.tar"
        with tarfile.open(archive, mode="w") as tar:
            root = tarfile.TarInfo("repository")
            root.type = tarfile.DIRTYPE
            root.mode = 0
            tar.addfile(root)
            member = tarfile.TarInfo("repository/tracked.txt")
            member.size = len(b"repository bytes")
            tar.addfile(member, io.BytesIO(b"repository bytes"))

        metadata = SnapshotMetadata(
            format_version=1,
            source_root_name="repository",
            archive_sha256="0" * 64,
            total_bytes=archive.stat().st_size,
            git_head=None,
            job_id="0" * 64,
        )
        destination = self.workspace / "readonly-output"
        destination.mkdir()
        fanout_module._extract_snapshot(archive, metadata, destination)
        root_path = destination / "repository"
        self.assertEqual(stat.S_IMODE(root_path.stat().st_mode), 0)
        os.chmod(root_path, 0o700)
        self.assertEqual((root_path / "tracked.txt").read_bytes(), b"repository bytes")

    def test_crafted_archive_links_are_rejected_before_extraction(self) -> None:
        archive = self.workspace / "crafted.tar"
        with tarfile.open(archive, mode="w") as tar:
            root = tarfile.TarInfo("repository")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            link = tarfile.TarInfo("repository/link")
            link.type = tarfile.SYMTYPE
            link.linkname = "tracked.txt"
            tar.addfile(link)

        metadata = SnapshotMetadata(
            format_version=1,
            source_root_name="repository",
            archive_sha256="0" * 64,
            total_bytes=archive.stat().st_size,
            git_head=None,
            job_id="0" * 64,
        )
        destination = self.workspace / "extracted"
        with self.assertRaises(FanoutError):
            fanout_module._extract_snapshot(archive, metadata, destination)
        self.assertFalse(destination.exists())

    def test_manifest_is_the_only_readiness_marker_for_partial_publication(self) -> None:
        claim, _ = self._claim(replication_count=1)

        def fail_manifest(*args: object, **kwargs: object) -> None:
            raise FanoutError("manifest publication blocked")

        with mock.patch.object(fanout_module, "_write_manifest_no_clobber", side_effect=fail_manifest):
            with self.assertRaises(FanoutError):
                materialize_claim(claim, self.candidate_root)

        job_dir = self.candidate_root / claim.packet.job_id
        self.assertTrue(job_dir.is_dir())
        self.assertFalse((job_dir / FANOUT_FILENAME).exists())
        self.assertTrue((job_dir / "candidate-001").is_dir())

    def test_materialize_oldest_claim_returns_none_for_empty_queue(self) -> None:
        self.assertIsNone(materialize_oldest_claim(self.queue_root, self.candidate_root))
    def test_manifest_sync_failure_rolls_back_readiness_marker(self) -> None:
        claim, _ = self._claim(replication_count=1)
        original_fsync = fanout_module._fsync_directory
        job_dir = self.candidate_root / claim.packet.job_id
        observations: list[bool] = []

        def fail_manifest_sync(path: Path) -> None:
            if path == job_dir:
                ready = (path / FANOUT_FILENAME).exists()
                observations.append(ready)
                if ready:
                    raise FanoutError("manifest directory sync blocked")
            original_fsync(path)

        with mock.patch.object(fanout_module, "_fsync_directory", side_effect=fail_manifest_sync):
            with self.assertRaises(FanoutError):
                materialize_claim(claim, self.candidate_root)

        self.assertTrue(job_dir.is_dir())
        self.assertFalse((job_dir / FANOUT_FILENAME).exists())
        self.assertIn([True, False], [observations[index : index + 2] for index in range(len(observations) - 1)])



    def test_cli_materialize_emits_only_safe_metadata(self) -> None:
        archive = self._snapshot("cli")
        prd = self.workspace / "cli.prd"
        prd_bytes = b"opaque review instructions never appear in output"
        prd.write_bytes(prd_bytes)
        deposit_packet(self.queue_root, archive, prd, replication_count=1)
        output = io.StringIO()

        with redirect_stdout(output):
            self.assertEqual(cli_main(["shared-materialize", str(self.queue_root), str(self.candidate_root)]), 0)

        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertTrue(payload["materialized"])
        self.assertEqual(payload["candidate_ids"], ["candidate-001"])
        self.assertNotIn(str(self.workspace), rendered)
        self.assertNotIn(prd_bytes.decode("ascii"), rendered)
        self.assertTrue((self.candidate_root / payload["job_id"] / FANOUT_FILENAME).is_file())

    def _claim(self, *, replication_count: int) -> tuple[object, bytes]:
        archive = self._snapshot("repository")
        prd = self.workspace / "review.prd"
        prd_bytes = b"opaque review instructions\x00must remain unparsed"
        prd.write_bytes(prd_bytes)
        deposit_packet(self.queue_root, archive, prd, replication_count=replication_count)
        claim = claim_oldest_packet(self.queue_root)
        assert claim is not None
        return claim, prd_bytes

    def _snapshot(self, name: str) -> Path:
        source = self.workspace / name
        source.mkdir(exist_ok=True)
        (source / "tracked.txt").write_bytes(b"repository bytes")
        git = source / ".git"
        git.mkdir(exist_ok=True)
        (git / "HEAD").write_text("ref: refs/heads/main\n", encoding="ascii")
        archive = self.workspace / f"{name}.tar.gz"
        return create_snapshot(source, archive).archive_path

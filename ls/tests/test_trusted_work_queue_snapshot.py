"""Contract fixtures for trusted full-repository snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path
_PACKAGE_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_PACKAGE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_TOOLS))

from trusted_work_queue.snapshot import (  # noqa: E402
    SnapshotError,
    SnapshotValidationError,
    create_snapshot,
    job_id_for_metadata,
    manifest_path_for,
    validate_snapshot,
)
import trusted_work_queue.snapshot as snapshot_module  # noqa: E402


class SnapshotContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.source = self.workspace / "repo"
        self.source.mkdir()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_hidden_and_git_entries_are_included(self) -> None:
        (self.source / ".git").mkdir()
        (self.source / ".git" / "HEAD").write_text(
            "0123456789abcdef0123456789abcdef01234567\n", encoding="ascii"
        )
        (self.source / ".hidden").write_text("hidden", encoding="ascii")
        archive = self.workspace / "repo.tar.gz"

        result = create_snapshot(self.source, archive)

        self.assertEqual(result.metadata.git_head, "0123456789abcdef0123456789abcdef01234567")
        with tarfile.open(archive, mode="r:gz") as tar:
            names = {member.name.rstrip("/") for member in tar}
        self.assertIn("repo/.git", names)
        self.assertIn("repo/.git/HEAD", names)
        self.assertIn("repo/.hidden", names)

    def test_symlink_and_permissions_are_retained(self) -> None:
        payload = self.source / "payload.txt"
        payload.write_text("payload", encoding="ascii")
        os.chmod(payload, 0o750)
        link = self.source / "payload-link"
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        os.symlink("payload.txt", link)
        archive = self.workspace / "repo.tar.gz"

        create_snapshot(self.source, archive)

        with tarfile.open(archive, mode="r:gz") as tar:
            payload_info = tar.getmember("repo/payload.txt")
            link_info = tar.getmember("repo/payload-link")
        self.assertEqual(stat.S_IMODE(payload_info.mode), 0o750)
        self.assertTrue(link_info.issym())
        self.assertEqual(link_info.linkname, "payload.txt")

    def test_unsafe_source_root_name_is_rejected(self) -> None:
        unsafe_source = self.workspace / "repo with spaces"
        self.source.rename(unsafe_source)

        with self.assertRaises(SnapshotError):
            create_snapshot(unsafe_source, self.workspace / "repo.tar.gz")

    def test_output_inside_source_is_rejected(self) -> None:
        with self.assertRaises(SnapshotError):
            create_snapshot(self.source, self.source / "snapshot.tar.gz")

    def test_existing_packet_paths_are_refused_without_mutation(self) -> None:
        archive = self.workspace / "repo.tar.gz"
        manifest = manifest_path_for(archive)
        archive_bytes = b"existing archive"
        manifest_bytes = b"existing manifest"
        archive.write_bytes(archive_bytes)
        manifest.write_bytes(manifest_bytes)

        with self.assertRaises(SnapshotError):
            create_snapshot(self.source, archive)

        self.assertEqual(archive.read_bytes(), archive_bytes)
        self.assertEqual(manifest.read_bytes(), manifest_bytes)

    def test_publication_collisions_do_not_replace_artifacts(self) -> None:
        archive = self.workspace / "race.tar.gz"
        manifest = manifest_path_for(archive)
        existing_archive = b"other publisher archive"
        original_scan = snapshot_module._scan_source_tree

        def create_archive_collision(source: Path) -> None:
            original_scan(source)
            archive.write_bytes(existing_archive)

        with mock.patch.object(
            snapshot_module,
            "_scan_source_tree",
            side_effect=create_archive_collision,
        ):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.source, archive)

        self.assertEqual(archive.read_bytes(), existing_archive)
        self.assertFalse(manifest.exists())

        manifest_collision_archive = self.workspace / "manifest-race.tar.gz"
        manifest_collision = manifest_path_for(manifest_collision_archive)
        existing_manifest = b"other publisher manifest"
        original_write_manifest = snapshot_module._write_manifest

        def create_manifest_collision(path: Path, metadata: object) -> None:
            path.write_bytes(existing_manifest)
            original_write_manifest(path, metadata)

        with mock.patch.object(
            snapshot_module,
            "_write_manifest",
            side_effect=create_manifest_collision,
        ):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.source, manifest_collision_archive)

        self.assertFalse(manifest_collision_archive.exists())
        self.assertEqual(manifest_collision.read_bytes(), existing_manifest)

    def test_parent_sync_failure_leaves_no_ready_marker(self) -> None:
        archive = self.workspace / "sync-failure.tar.gz"
        manifest = manifest_path_for(archive)
        original_fsync_parent = snapshot_module._fsync_parent
        calls = 0

        def fail_manifest_sync(path: Path) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise SnapshotError("simulated parent fsync failure")
            original_fsync_parent(path)

        with mock.patch.object(
            snapshot_module,
            "_fsync_parent",
            side_effect=fail_manifest_sync,
        ):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.source, archive)

        self.assertFalse(archive.exists())
        self.assertFalse(manifest.exists())

    def test_changed_git_head_aborts_before_publication(self) -> None:
        archive = self.workspace / "head-change.tar.gz"
        manifest = manifest_path_for(archive)
        before = "0123456789abcdef0123456789abcdef01234567"
        after = "fedcba9876543210fedcba9876543210fedcba98"

        with mock.patch.object(
            snapshot_module,
            "_discover_git_head",
            side_effect=[before, after],
        ):
            with self.assertRaises(SnapshotError):
                create_snapshot(self.source, archive)

        self.assertFalse(archive.exists())
        self.assertFalse(manifest.exists())

    @unittest.skipUnless(hasattr(os, "mkfifo"), "FIFOs are unavailable")
    def test_source_special_member_is_rejected(self) -> None:
        os.mkfifo(self.source / "unsupported.fifo")
        with self.assertRaises(SnapshotError):
            create_snapshot(self.source, self.workspace / "repo.tar.gz")

    def test_tampering_is_detected(self) -> None:
        archive = self.workspace / "repo.tar.gz"
        create_snapshot(self.source, archive)
        with archive.open("ab") as handle:
            handle.write(b"tampered")

        with self.assertRaises(SnapshotValidationError):
            validate_snapshot(archive)

    def test_member_outside_single_root_is_rejected(self) -> None:
        archive = self.workspace / "malicious.tar.gz"
        with tarfile.open(archive, mode="w:gz") as tar:
            root = tarfile.TarInfo("repo")
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            tar.addfile(root)
            escape = tarfile.TarInfo("repo/../escape")
            escape.size = 0
            tar.addfile(escape)
        self._write_manifest_for_archive(archive, "repo")

        with self.assertRaises(SnapshotValidationError):
            validate_snapshot(archive)

    def test_archive_special_member_is_rejected_without_extracting(self) -> None:
        archive = self.workspace / "special.tar.gz"
        with tarfile.open(archive, mode="w:gz") as tar:
            root = tarfile.TarInfo("repo")
            root.type = tarfile.DIRTYPE
            tar.addfile(root)
            fifo = tarfile.TarInfo("repo/fifo")
            fifo.type = tarfile.FIFOTYPE
            tar.addfile(fifo)
        self._write_manifest_for_archive(archive, "repo")

        with self.assertRaises(SnapshotValidationError):
            validate_snapshot(archive)

    def _write_manifest_for_archive(self, archive: Path, root_name: str) -> None:
        digest = hashlib.sha256()
        with archive.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest = digest.hexdigest()
        total_bytes = archive.stat().st_size
        job_id = job_id_for_metadata(
            format_version=1,
            source_root_name=root_name,
            archive_sha256=digest,
            total_bytes=total_bytes,
            git_head=None,
        )
        payload = {
            "format_version": 1,
            "source_root_name": root_name,
            "archive_sha256": digest,
            "total_bytes": total_bytes,
            "git_head": None,
            "job_id": job_id,
            "job_identity": None,
            "prd_identity": None,
            "master_remote": None,
            "master_ref": None,
            "source_fork": None,
        }
        manifest_path_for(archive).write_text(
            json.dumps(payload, sort_keys=True), encoding="ascii"
        )


if __name__ == "__main__":
    unittest.main()

"""Contract tests for opaque returned patch validation."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from unittest import mock
import unittest
from pathlib import Path

_PACKAGE_TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(_PACKAGE_TOOLS) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_TOOLS))

from trusted_work_queue.result_validation import (  # noqa: E402
    FANOUT_FILENAME,
    PATCH_FILENAME,
    RESULT_FILENAME,
    ResultValidationError,
    validate_patch_result,
)
import trusted_work_queue.result_validation as result_validation_module  # noqa: E402


class ReturnedPatchValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self._temporary.name)
        self.job_id = "a" * 64
        self.archive_sha256 = "b" * 64
        self.prd_sha256 = "c" * 64
        self.fanout = self.workspace / FANOUT_FILENAME
        self._write_fanout()

    def tearDown(self) -> None:
        self._temporary.cleanup()

    def test_valid_patch_binds_to_fanout_candidate_and_snapshot(self) -> None:
        result_dir = self._result_dir("valid", candidate_id="candidate-002", patch=b"diff --git a/a b/a\n")

        result = validate_patch_result(self.fanout, result_dir)

        self.assertEqual(result.job_id, self.job_id)
        self.assertEqual(result.candidate_id, "candidate-002")
        self.assertEqual(result.archive_sha256, self.archive_sha256)
        self.assertEqual(result.patch_path.read_bytes(), b"diff --git a/a b/a\n")

    def test_snapshot_or_candidate_mismatch_is_rejected(self) -> None:
        result_dir = self._result_dir("candidate", candidate_id="candidate-999", patch=b"patch")
        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

        result_dir = self._result_dir("digest", candidate_id="candidate-001", patch=b"patch")
        payload = json.loads((result_dir / RESULT_FILENAME).read_text(encoding="ascii"))
        payload["archive_sha256"] = "d" * 64
        (result_dir / RESULT_FILENAME).write_text(json.dumps(payload, sort_keys=True), encoding="ascii")
        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

    def test_tampered_patch_and_unsafe_result_members_are_rejected(self) -> None:
        result_dir = self._result_dir("tampered", candidate_id="candidate-001", patch=b"expected")
        (result_dir / PATCH_FILENAME).write_bytes(b"changed")
        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

        if hasattr(os, "symlink"):
            unsafe = self._result_dir("symlink", candidate_id="candidate-001", patch=b"patch")
            (unsafe / PATCH_FILENAME).unlink()
            os.symlink(self.workspace / "outside", unsafe / PATCH_FILENAME)
            with self.assertRaises(ResultValidationError):
                validate_patch_result(self.fanout, unsafe)

    def test_patch_swapped_to_symlink_after_manifest_read_is_rejected(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable on this platform")
        patch = b"patch bytes"
        result_dir = self._result_dir("swap", candidate_id="candidate-001", patch=patch)
        outside = self.workspace / "outside.patch"
        outside.write_bytes(patch)
        original_read = result_validation_module._read_json_descriptor

        def replace_patch_after_manifest(descriptor: int, *, field: str) -> dict[str, object]:
            payload = original_read(descriptor, field=field)
            if field == "result manifest":
                patch_path = result_dir / PATCH_FILENAME
                patch_path.unlink()
                os.symlink(outside, patch_path)
            return payload

        with mock.patch.object(
            result_validation_module,
            "_read_json_descriptor",
            side_effect=replace_patch_after_manifest,
        ):
            with self.assertRaises(ResultValidationError):
                validate_patch_result(self.fanout, result_dir)

    def test_unsupported_manifest_schema_is_rejected(self) -> None:
        result_dir = self._result_dir("schema", candidate_id="candidate-001", patch=b"patch")
        payload = json.loads((result_dir / RESULT_FILENAME).read_text(encoding="ascii"))
        payload["unexpected"] = "field"
        (result_dir / RESULT_FILENAME).write_text(json.dumps(payload, sort_keys=True), encoding="ascii")

        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

    def test_extra_result_member_is_rejected(self) -> None:
        result_dir = self._result_dir("extra-member", candidate_id="candidate-001", patch=b"patch")
        (result_dir / "unexpected.bin").write_bytes(b"unexpected")

        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

    def test_noncanonical_fanout_candidate_paths_are_rejected(self) -> None:
        result_dir = self._result_dir("fanout-path", candidate_id="candidate-001", patch=b"patch")
        payload = json.loads(self.fanout.read_text(encoding="ascii"))
        payload["candidates"][0]["repository"] = "candidate-001/elsewhere"
        self.fanout.write_text(json.dumps(payload, sort_keys=True), encoding="ascii")

        with self.assertRaises(ResultValidationError):
            validate_patch_result(self.fanout, result_dir)

    def _write_fanout(self) -> None:
        self.fanout.write_text(
            json.dumps(
                {
                    "format_version": 1,
                    "job_id": self.job_id,
                    "archive_sha256": self.archive_sha256,
                    "archive_bytes": 123,
                    "git_head": "0123456789abcdef0123456789abcdef01234567",
                    "source_root_name": "repository",
                    "prd_sha256": self.prd_sha256,
                    "prd_bytes": 9,
                    "replication_count": 2,
                    "claim_retained": True,
                    "candidates": [
                        {"candidate_id": "candidate-001", "repository": "candidate-001/repository", "prd": "candidate-001/prd.bin"},
                        {"candidate_id": "candidate-002", "repository": "candidate-002/repository", "prd": "candidate-002/prd.bin"},
                    ],
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="ascii",
        )

    def _result_dir(self, name: str, *, candidate_id: str, patch: bytes) -> Path:
        directory = self.workspace / name
        directory.mkdir()
        (directory / PATCH_FILENAME).write_bytes(patch)
        payload = {
            "format_version": 1,
            "job_id": self.job_id,
            "candidate_id": candidate_id,
            "archive_sha256": self.archive_sha256,
            "git_head": "0123456789abcdef0123456789abcdef01234567",
            "patch_sha256": hashlib.sha256(patch).hexdigest(),
            "patch_bytes": len(patch),
        }
        (directory / RESULT_FILENAME).write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
        return directory

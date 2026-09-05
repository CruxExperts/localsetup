"""Inspect tar/wheel SDK bytes without importing code or extracting an archive."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import tarfile
import tempfile
import zipfile

from .integrity import _relative, verify
from .sbom import SBOM_PATH, document

MAX_FILE = 16 * 1024 * 1024
MAX_PAYLOAD = 64 * 1024 * 1024


def _payload_location(name: str) -> tuple[str, str] | None:
    # Public tar, ordinary wheel, or one sdist wrapper directory.
    for base in ("vendor/lscli", "ls/_sdk_payload"):
        candidates = [base]
        parts = PurePosixPath(name).parts
        if len(parts) > 1:
            candidates.append(parts[0] + "/" + base)
        for prefix in candidates:
            if name == prefix or name.startswith(prefix + "/"):
                return prefix, name[len(prefix):].lstrip("/")
    return None


def inspect_artifact(path: Path, *, required: bool = True, expected_digest: str | None = None,
                     check_embedded_sbom: bool = True) -> dict | None:
    """Verify SDK files and, for wheels, the embedded SDK-only SBOM.

    Only bounded regular SDK files are materialized into a fresh temporary
    directory. Archive paths, permissions, links, and unrelated files are never
    extracted. The manifest is artifact evidence, not a separate trust anchor.
    """
    roots = set()
    seen = set()
    non_directories = set()
    total = 0
    embedded = None
    is_wheel = path.suffix == ".whl"
    with tempfile.TemporaryDirectory(prefix="sdk-payload-") as tmp:
        root = Path(tmp)

        def consume(name, size, regular, directory, read):
            nonlocal total, embedded
            canonical = _relative(name.rstrip("/"))
            if not directory:
                non_directories.add(canonical)
            if is_wheel:
                if name.startswith(("pydantic_ai/", "pydantic_graph/", "pydantic_ai_harness/")):
                    raise ValueError("SDK namespace exposed at wheel root")
            location = _payload_location(name)
            if name == SBOM_PATH and is_wheel:
                if embedded is not None or not regular or size > MAX_FILE:
                    raise ValueError("Invalid or duplicate embedded SDK SBOM")
                embedded = read()
            if location is None:
                return
            _relative(name.rstrip("/"))
            prefix, relative = location
            _relative(prefix)
            if is_wheel and prefix != "ls/_sdk_payload":
                raise ValueError("Wheel SDK payload has the wrong location")
            if not is_wheel and not prefix.endswith("vendor/lscli"):
                raise ValueError("Source archive SDK payload has the wrong location")
            roots.add(prefix)
            if len(roots) != 1:
                raise ValueError("Ambiguous SDK payload roots")
            if directory:
                if relative:
                    _relative(relative.rstrip("/"))
                return
            if not regular or not relative:
                raise ValueError("SDK archive member must be a regular file")
            _relative(relative)
            if relative in seen or size < 0 or size > MAX_FILE:
                raise ValueError("Duplicate or oversized SDK archive member")
            seen.add(relative)
            total += size
            if total > MAX_PAYLOAD or len(seen) > 10000:
                raise ValueError("SDK archive exceeds inventory limits")
            content = read()
            if len(content) != size:
                raise ValueError("SDK archive member size mismatch")
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)

        if is_wheel:
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    mode = member.external_attr >> 16
                    kind = stat.S_IFMT(mode)
                    regular = kind in (0, stat.S_IFREG) and not member.is_dir()
                    consume(member.filename, member.file_size, regular, member.is_dir() and kind in (0, stat.S_IFDIR), lambda m=member: archive.read(m))
        else:
            with tarfile.open(path, "r:*") as archive:
                for member in archive:
                    consume(member.name, member.size, member.isfile(), member.isdir(),
                            lambda m=member: archive.extractfile(m).read(MAX_FILE + 1))
        if not roots:
            if required or expected_digest is not None or embedded is not None:
                raise ValueError("SDK payload is missing from artifact")
            return None
        prefix = next(iter(roots))
        if any(str(parent) in non_directories for parent in PurePosixPath(prefix).parents):
            raise ValueError("SDK archive ancestor is not a directory")
        manifest = verify(root)
        digest = hashlib.sha256((root / "manifest.json").read_bytes()).hexdigest()
        if expected_digest is not None and digest != expected_digest:
            raise ValueError("SDK manifest differs from artifact metadata")
        if is_wheel and check_embedded_sbom:
            if embedded is None or json.loads(embedded) != document(manifest):
                raise ValueError("Embedded SDK SBOM differs from verified payload")
        return {"manifest": manifest, "manifest_sha256": digest}

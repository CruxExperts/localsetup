"""Validate a payload without importing or executing third-party code.

The manifest is a build/release input, not an independent trust anchor. A protected
runtime must authenticate its artifact and protect both manifest and payload.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

COMPONENTS = {
    "pydantic-ai-slim": "pydantic_ai",
    "pydantic-graph": "pydantic_graph",
    "pydantic-ai-harness": "pydantic_ai_harness",
}
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError("Payload path must be a nonempty POSIX relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError("Unsafe or noncanonical payload path")
    return value


def _digest(value: object) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError("Invalid SHA-256 digest")
    return value


def _walk_error(error: OSError) -> None:
    raise error


def _regular_files(root: Path) -> set[str]:
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Payload root must be a regular directory")
    result = set()
    for parent, directories, files in os.walk(root, followlinks=False, onerror=_walk_error):
        for name in directories + files:
            path = Path(parent) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                raise ValueError("Payload contains a symlink or special file")
            if stat.S_ISREG(mode):
                result.add(path.relative_to(root).as_posix())
    return result


def _component_metadata(component: dict) -> None:
    name = component["name"]
    version = component.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ValueError("Missing or invalid component release version")
    commit = component.get("commit")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Missing or invalid immutable source commit")
    repository = "https://github.com/pydantic/" + (
        "pydantic-ai-harness" if name == "pydantic-ai-harness" else "pydantic-ai")
    if component.get("repository") != repository:
        raise ValueError("Unexpected upstream repository")
    expected_url = repository.replace("github.com", "codeload.github.com") + "/tar.gz/" + commit
    if component.get("source_archive_url") != expected_url:
        raise ValueError("Source archive URL disagrees with immutable repository commit")
    _digest(component.get("source_archive_sha256"))
    sdist = component.get("sdist")
    expected_name = name.replace("-", "_") + "-" + version + ".tar.gz"
    if not isinstance(sdist, dict) or sdist.get("name") != expected_name:
        raise ValueError("Missing or invalid source distribution identity")
    digest = sdist.get("digest")
    if not isinstance(digest, dict) or set(digest) != {"sha256"}:
        raise ValueError("Missing source distribution digest")
    _digest(digest["sha256"])
    prefix = {"pydantic-ai-slim": "pydantic_ai_slim/", "pydantic-graph": "pydantic_graph/",
              "pydantic-ai-harness": ""}[name]
    if component.get("source_prefix") != prefix:
        raise ValueError("Unexpected source archive prefix")
    provenance = component.get("provenance")
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError("Missing provenance verification description")


def verify(root: Path) -> dict:
    """Return validated metadata; raise on missing, extra, or changed payload data.

    Call only on a stable tree held under the owning runtime/build lock. This
    static check does not defend against a concurrent privileged writer.
    """
    actual = _regular_files(root)
    manifest_path = root / "manifest.json"
    if "manifest.json" not in actual or manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError("Missing or oversized payload manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("Unsupported payload manifest")
    components = manifest.get("components")
    if not isinstance(components, list) or len(components) != len(COMPONENTS):
        raise ValueError("Payload component set is incomplete")
    if any(not isinstance(c, dict) for c in components):
        raise ValueError("Invalid component record")
    if {c.get("name") for c in components} != set(COMPONENTS):
        raise ValueError("Unexpected payload component")
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Payload inventory is empty")
    for name, entry in entries.items():
        _relative(name)
        if not isinstance(entry, dict) or entry.get("component") not in COMPONENTS:
            raise ValueError("Invalid payload file owner")
        _digest(entry.get("sha256"))
        role = entry.get("role")
        namespace = COMPONENTS[entry["component"]]
        if role == "runtime":
            if not name.startswith(namespace + "/"):
                raise ValueError("Runtime file is outside its namespace")
            _digest(entry.get("upstream_sha256"))
        elif role not in {"license", "patch"} or not name.startswith({"license": "licenses/", "patch": "patches/"}[role]):
            raise ValueError("Invalid payload file role or location")
    if actual != set(entries) | {"manifest.json"}:
        raise ValueError("Payload files differ from the exact manifest inventory")
    for name, entry in entries.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Payload digest mismatch: {name}")
    for component in components:
        _component_metadata(component)
        name = component["name"]
        namespace = COMPONENTS[name]
        if component.get("namespace") != namespace or component.get("license") != "MIT":
            raise ValueError("Invalid namespace or license declaration")
        license_entry = entries.get(_relative(component.get("license_file")), {})
        if license_entry.get("role") != "license" or license_entry.get("component") != name:
            raise ValueError("Missing component license")
        if namespace + "/__init__.py" not in entries:
            raise ValueError("Missing namespace initializer")
    patches = manifest.get("patches")
    if not isinstance(patches, list):
        raise ValueError("Missing patch inventory")
    targets = set()
    patch_paths = set()
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("Invalid patch record")
        path = _relative(patch.get("path"))
        target = _relative(patch.get("target"))
        entry, target_entry = entries.get(path, {}), entries.get(target, {})
        if (entry.get("role") != "patch" or target_entry.get("role") != "runtime"
                or entry.get("sha256") != _digest(patch.get("sha256"))
                or entry.get("component") != target_entry.get("component")
                or path in patch_paths or target in targets):
            raise ValueError("Patch inventory disagrees with payload")
        targets.add(target)
        patch_paths.add(path)
    changed = {name for name, entry in entries.items()
               if entry["role"] == "runtime" and entry["sha256"] != entry["upstream_sha256"]}
    if targets != changed or patch_paths != {name for name, e in entries.items() if e["role"] == "patch"}:
        raise ValueError("Every upstream change requires one recorded patch")
    return manifest

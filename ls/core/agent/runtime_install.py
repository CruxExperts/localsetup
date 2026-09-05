"""Explicit offline runtime installation with leased, recoverable selection."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
from email.parser import BytesParser
import json
import math
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import subprocess
import sys
import time
import uuid
import zipfile

from ..sdk_payload.artifacts import inspect_artifact
from ..sdk_payload.dependency_integrity import regular_bytes
from ..versioning_models import SemVer
from .runtime_lock import runtime_use

MAX_WHEEL_BYTES = 256 * 1024 * 1024
DIGEST = re.compile(r"[0-9a-f]{64}\Z")


def _wheel_bytes(path: Path) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("Framework wheel must be a regular file without symlinks")
    with path.open('rb') as stream:
        data = stream.read(MAX_WHEEL_BYTES + 1)
    if len(data) > MAX_WHEEL_BYTES:
        raise ValueError("Framework wheel exceeds the 256 MiB installation limit")
    return data


def workspace_root(path: Path) -> Path:
    """Treat enclosing repositories as part of the editable workspace boundary."""
    path = path.resolve()
    result = path
    for parent in (path, *path.parents):
        marker = parent / '.git'
        if marker.exists() or marker.is_symlink():
            result = parent
    return result


def plan(root: Path, wheel: Path, digest: str, wheelhouse: Path, workspace: Path) -> dict:
    if not DIGEST.fullmatch(digest):
        raise ValueError("Expected a lowercase SHA-256 digest from a trusted artifact source")
    root, workspace = root.absolute(), workspace_root(workspace)
    if ".." in root.parts:
        raise ValueError("Runtime root must be canonical")
    if root.resolve().is_relative_to(workspace) or workspace.is_relative_to(root.resolve()):
        raise ValueError("Managed runtime and workspace must be separate trees")
    if wheel.suffix != '.whl' or hashlib.sha256(_wheel_bytes(wheel)).hexdigest() != digest:
        raise ValueError("Framework wheel digest does not match")
    inspect_artifact(wheel)
    with zipfile.ZipFile(wheel) as archive:
        metadata = [x for x in archive.infolist() if x.filename.endswith('.dist-info/METADATA')]
        if len(metadata) != 1 or metadata[0].file_size > 1024 * 1024:
            raise ValueError("Framework wheel metadata is ambiguous or oversized")
        identity = BytesParser().parsebytes(archive.read(metadata[0]))
        if identity.get('Name') != 'localsetup':
            raise ValueError("Expected the framework distribution")
        version = str(SemVer.parse(identity.get('Version', '')))
    if not wheelhouse.is_dir() or wheelhouse.is_symlink():
        raise ValueError("An existing local dependency artifact directory is required")
    return {"schema_version": 1, "version": version, "workspace": str(workspace), "root": str(root), "wheel": str(wheel.absolute()),
            "sha256": digest, "wheelhouse": str(wheelhouse.absolute()),
            "release": str(root / digest), "offline": True}


def _ensure_root(root: Path) -> None:
    for path in (*reversed(root.parents), root):
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("Runtime path must contain only directories, without symlinks")
        path.mkdir(mode=0o700, exist_ok=True)


def _write_json(path: Path, value: dict) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("Runtime record must be a regular file")
    temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            os.chmod(temporary, 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    finally:
        temporary.unlink(missing_ok=True)


def _run(command: list[str], *, directory: Path, deadline: float, environment: dict) -> None:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Runtime installation deadline expired")
    process = subprocess.Popen(command, cwd=directory, env=environment, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        if process.wait(timeout=remaining):
            raise RuntimeError("Runtime installation command failed; incomplete release retained")
    finally:
        # Build descendants must not outlive their owning installation command.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _populate(release: Path, wheel: Path, wheelhouse: Path, uv: str, deadline: float) -> None:
    environment = {key: value for key, value in os.environ.items() if key in {'PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT'}}
    environment.update(HOME=str(release / 'home'), UV_CACHE_DIR=str(release / 'cache'), UV_PYTHON_DOWNLOADS='never')
    with zipfile.ZipFile(wheel) as archive:
        for name in ('sdk-runtime.lock', 'sdk-build.lock'):
            (release / name).write_bytes(archive.read('ls/config/' + name))
    python = release / 'venv/bin/python'
    commands = [
        [uv, '--no-config', 'venv', '--offline', '--python', sys.executable, str(release / 'venv')],
        [uv, '--no-config', 'pip', 'install', '--python', str(python), '--offline', '--no-index',
         '--find-links', str(wheelhouse), '--require-hashes', '--only-binary', ':all:', '-r', str(release / 'sdk-build.lock')],
        [uv, '--no-config', 'pip', 'install', '--python', str(python), '--offline', '--no-index',
         '--find-links', str(wheelhouse), '--require-hashes', '--no-build-isolation', '-r', str(release / 'sdk-runtime.lock')],
        [uv, '--no-config', 'pip', 'install', '--python', str(python), '--offline', '--no-deps', str(wheel)],
        [uv, '--no-config', 'pip', 'check', '--python', str(python)],
        [str(python), '-I', '-c', "from ls.core.agent.diagnostics import inspect; assert inspect()['sdk_payload'] == 'verified'"],
    ]
    for command in commands:
        _run(command, directory=release, deadline=deadline, environment=environment)
    # Managed entry points must not honor workspace PYTHONPATH or user site hooks.
    launcher = release / 'venv/bin/lscli'
    if launcher.is_symlink() or not launcher.is_file():
        raise ValueError("Managed CLI launcher must be a regular file")
    launcher.write_text('#!/bin/sh\nexec ' + shlex.quote(str(python)) + ' -I -m ls.core.agent.cli "$@"\n')
    launcher.chmod(0o700)


def install(root: Path, wheel: Path, digest: str, wheelhouse: Path, workspace: Path, *, timeout: float = 300) -> dict:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Installation timeout must be finite and positive")
    specification = plan(root, wheel, digest, wheelhouse, workspace)
    root = Path(specification['root'])
    uv = shutil.which('uv')
    if uv is None:
        raise RuntimeError("Runtime installation requires the uv CLI")
    deadline = time.monotonic() + timeout
    _ensure_root(root)
    with runtime_use(root, exclusive=True, timeout=max(0, deadline - time.monotonic())):
        release = root / digest
        if release.exists() or release.is_symlink():
            raise ValueError("Release slot already exists; inspect retained state instead of replaying installation")
        previous = _selection(root)
        release.mkdir(mode=0o700)
        _write_json(release / 'status.json', {'schema_version': 1, 'status': 'incomplete', 'sha256': digest})
        local_wheel = release / wheel.name
        local_wheel.write_bytes(_wheel_bytes(wheel))
        if hashlib.sha256(local_wheel.read_bytes()).hexdigest() != digest:
            raise ValueError("Framework artifact changed during installation")
        _populate(release, local_wheel, Path(specification['wheelhouse']), uv, deadline)
        if time.monotonic() > deadline:
            raise TimeoutError("Runtime installation deadline expired before activation")
        result = {'schema_version': 1, 'status': 'installed', 'sha256': digest,
                  'previous': previous.get('sha256') if previous else None}
        _write_json(release / 'status.json', result)
        _write_json(root / 'current.json', result)
        return result


def _selection(root: Path) -> dict | None:
    pointer = root / 'current.json'
    if not pointer.exists() and not pointer.is_symlink():
        return None
    result = json.loads(regular_bytes(pointer))
    if not isinstance(result, dict) or result.get('schema_version') != 1 or result.get('status') != 'installed' or not isinstance(result.get('sha256'), str) or not DIGEST.fullmatch(result['sha256']):
        raise ValueError("Invalid runtime selection")
    return result


@contextmanager
def selected(root: Path, *, timeout: float = 30):
    """Keep the shared lease for the entire caller-owned worker lifetime."""
    with runtime_use(root, timeout=timeout):
        selection = _selection(root)
        if selection is None:
            raise ValueError("No installed runtime selected")
        release = root / selection['sha256']
        if json.loads(regular_bytes(release / 'status.json')) != selection:
            raise ValueError("Selected release does not match its completed installation record")
        yield release

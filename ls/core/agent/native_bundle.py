"""Bounded, explicitly authenticated native sandbox payloads; no host fallback."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import platform
import re
import stat
import sys
import zipfile

MAX_BYTES = 16 * 1024 * 1024
FILES = ('bwrap', 'bubblewrap-COPYING', 'libcap-copyright')
DIGEST = re.compile(r'[0-9a-f]{64}\Z')
COMPONENTS = {
    'bubblewrap': {'version': '0.12.0', 'source_sha256': '9760d007363e3abba7c747489910f9f82d9fca53ba3bd3282e396fa3c97a3314'},
    'libcap': {'version': '2.66-5ubuntu2.4', 'artifact_sha256': '07f2462867569a2119a2ad0f1593232663f2d1612b791c230d22a8d73a15abee'},
}
TARGET = {'os': 'linux', 'machine': 'x86_64', 'libc': 'glibc', 'minimum_libc': '2.39'}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate native manifest key')
        result[key] = value
    return result


def _platform() -> None:
    libc, version = platform.libc_ver()
    parts = version.split('.')
    if (sys.platform != 'linux' or platform.machine() != 'x86_64' or libc != 'glibc'
            or len(parts) < 2 or not all(x.isdigit() for x in parts)
            or tuple(map(int, parts)) < (2, 39)):
        raise ValueError('Native sandbox bundle requires Linux x86_64 with glibc >= 2.39')


def read(path: Path, digest: str) -> dict[str, bytes]:
    """Validate bytes without executing the payload or creating persistent state."""
    if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
        raise ValueError('Expected a trusted native bundle SHA-256 digest')
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('Native bundle must be a regular file without symlinks')
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('Native bundle digest mismatch or size limit exceeded')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) != 4 or {x.filename for x in entries} != {*FILES, 'manifest.json'}:
                raise ValueError('Unexpected native bundle inventory')
            if any(x.file_size <= 0 or x.file_size > MAX_BYTES or x.flag_bits & 1
                   or stat.S_IFMT(x.external_attr >> 16) not in (0, stat.S_IFREG) for x in entries):
                raise ValueError('Native bundle requires bounded regular files')
            if sum(x.file_size for x in entries) > MAX_BYTES:
                raise ValueError('Native bundle expanded size limit exceeded')
            contents = {x.filename: archive.read(x) for x in entries}
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError) as exc:
        raise ValueError('Invalid native bundle archive') from exc
    if len(contents['manifest.json']) > 16384:
        raise ValueError('Native manifest is oversized')
    manifest = json.loads(contents['manifest.json'], object_pairs_hook=_unique)
    expected = {'schema_version': 1, 'target': TARGET, 'components': COMPONENTS,
                'files': {name: hashlib.sha256(contents[name]).hexdigest() for name in FILES}}
    if manifest != expected or type(manifest.get('schema_version')) is not int:
        raise ValueError('Unsupported native manifest or content digest mismatch')
    if not contents['bwrap'].startswith(b'\x7fELF\x02\x01'):
        raise ValueError('Native sandbox executable must be a 64-bit little-endian ELF')
    _platform()
    return contents


def identity(wheel_digest: str, bundle_digest: str) -> str:
    return hashlib.sha256(('lscli-runtime-v1\n' + wheel_digest + '\n' + bundle_digest + '\n').encode()).hexdigest()


def materialize(release: Path, contents: dict[str, bytes]) -> None:
    """Write only beneath the newly populated environment, before integrity sealing."""
    destination = release / 'venv' / 'lscli-native'
    destination.mkdir(mode=0o700)
    for name, data in contents.items():
        path = destination / name
        with path.open('xb') as stream:
            stream.write(data)
        path.chmod(0o700 if name == 'bwrap' else 0o600)

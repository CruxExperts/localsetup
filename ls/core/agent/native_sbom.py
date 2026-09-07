"""Deterministic external native SBOMs; bundle authentication is not build attestation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from . import native_bundle as native

MAX_SBOM_BYTES = 128 * 1024
LICENSE_HASHES = {
    'bubblewrap-COPYING': 'dc626520dcd53a22f727af3ee42c770e56c97a64fe3adb063799d8ab032fe551',
    'libcap-copyright': 'e60a5642e12e340060e4e519a65b2eb0330be2917854841c644e36268f607d54',
}
# Declarations from the supported source/notice baseline, not a legal assessment.
LICENSES = {
    'bubblewrap': 'LGPL-2.0-or-later AND LGPL-2.1-or-later',
    'libcap': '(BSD-3-Clause OR GPL-2.0-only) AND (BSD-3-Clause OR GPL-2.0-or-later)',
}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _hash(digest: str) -> list[dict]:
    return [{'alg': 'SHA-256', 'content': digest}]


def _properties(values: dict[str, str]) -> list[dict]:
    return [{'name': 'localsetup:native:' + key, 'value': value} for key, value in sorted(values.items())]


def _encode(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode('utf-8')


def document(bundle: Path, trusted_sha256: str) -> dict:
    """Bind exact authenticated output and declared inputs, without running native code."""
    contents = native.read_static(bundle, trusted_sha256)
    for name, expected in LICENSE_HASHES.items():
        if _sha(contents[name]) != expected:
            raise ValueError('Unsupported native license notice bytes')
    manifest = json.loads(contents['manifest.json'])
    versions = manifest['components']
    bundle_ref = 'urn:sha256:' + trusted_sha256
    bubble_ref, cap_ref = 'native:bubblewrap', 'native:libcap'
    bubble = {
        'type': 'application', 'bom-ref': bubble_ref, 'name': 'bubblewrap',
        'version': versions['bubblewrap']['version'],
        'purl': 'pkg:generic/bubblewrap@' + versions['bubblewrap']['version'],
        'hashes': _hash(_sha(contents['bwrap'])),
        'licenses': [{'expression': LICENSES['bubblewrap']}],
        'properties': _properties({
            'output-entry': 'bwrap', 'license-entry': 'bubblewrap-COPYING',
            'license-sha256': _sha(contents['bubblewrap-COPYING']),
            'source-input-kind': 'source-archive',
            'source-input-sha256': versions['bubblewrap']['source_sha256'],
            'source-declarations': 'LGPL-2.0-or-later; safe_openat.c: LGPL-2.1-or-later',
        }),
    }
    cap = {
        'type': 'library', 'bom-ref': cap_ref, 'name': 'libcap',
        'version': versions['libcap']['version'],
        'purl': 'pkg:generic/libcap@' + versions['libcap']['version'],
        'licenses': [{'expression': LICENSES['libcap']}],
        'properties': _properties({
            'linkage': 'static', 'incorporated-in': bubble_ref,
            'license-entry': 'libcap-copyright', 'license-sha256': _sha(contents['libcap-copyright']),
            'build-input-kind': 'debian-binary-package',
            'build-input-purl': 'pkg:deb/ubuntu/libcap-dev@1%3A' + versions['libcap']['version'] + '?arch=amd64',
            'build-input-version': '1:' + versions['libcap']['version'],
            'build-input-sha256': versions['libcap']['artifact_sha256'],
            'input-hash-scope': 'libcap-dev .deb, not corresponding source, linked archive or output binary',
            'notice-declarations': 'library: BSD-3-Clause OR GPL-2.0-only; Debian packaging/patches: BSD-3-Clause OR GPL-2.0-or-later',
        }),
    }
    properties = {'manifest-schema': str(manifest['schema_version']),
                  'evidence-scope': 'authenticated bundle inventory and supported input declarations; no build attestation'}
    properties.update({'entry-sha256:' + name: _sha(raw) for name, raw in contents.items()})
    properties.update({'host-requirement:' + name: value for name, value in manifest['target'].items()})
    return {
        'bomFormat': 'CycloneDX', 'specVersion': '1.6', 'version': 1,
        'metadata': {'component': {'type': 'application', 'name': 'LSCli native sandbox bundle',
                                   'bom-ref': bundle_ref, 'hashes': _hash(trusted_sha256),
                                   'properties': _properties(properties)}},
        'components': [bubble, cap],
        'dependencies': [{'ref': bundle_ref, 'dependsOn': [bubble_ref]},
                         {'ref': bubble_ref, 'dependsOn': [cap_ref]},
                         {'ref': cap_ref, 'dependsOn': []}],
    }


def encode(bundle: Path, trusted_sha256: str) -> bytes:
    return _encode(document(bundle, trusted_sha256))


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate native SBOM key')
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError('Nonfinite native SBOM value')


def verify(bundle: Path, trusted_sha256: str, sidecar: Path) -> dict:
    expected = encode(bundle, trusted_sha256)
    if any(path.is_symlink() for path in (sidecar, *sidecar.parents)) or not sidecar.is_file():
        raise ValueError('Native SBOM must be a regular file without symlinks')
    with sidecar.open('rb') as stream:
        raw = stream.read(MAX_SBOM_BYTES + 1)
    if len(raw) > MAX_SBOM_BYTES:
        raise ValueError('Native SBOM size limit exceeded')
    try:
        value = json.loads(raw, object_pairs_hook=_unique, parse_constant=_nonfinite)
        canonical = _encode(value)
    except (ValueError, RecursionError) as exc:
        raise ValueError('Invalid native SBOM JSON') from exc
    # Canonical JSON comparison preserves numeric types and rejects all extra records.
    if canonical != expected:
        raise ValueError('Native SBOM differs from authenticated bundle records')
    return {'ok': True, 'bundle_sha256': trusted_sha256, 'sbom_sha256': _sha(raw)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('emit', 'verify'):
        child = commands.add_parser(command)
        child.add_argument('--bundle', type=Path, required=True)
        child.add_argument('--sha256', required=True, help='Independently trusted bundle SHA-256')
        child.add_argument('--out' if command == 'emit' else '--sbom', type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == 'emit':
            raw = encode(args.bundle, args.sha256)
            with args.out.open('xb') as stream:
                stream.write(raw)
            result = {'ok': True, 'bundle_sha256': args.sha256, 'sbom_sha256': _sha(raw)}
        else:
            result = verify(args.bundle, args.sha256, args.sbom)
    except (ValueError, OSError) as exc:
        result = {'ok': False, 'error': str(exc) if isinstance(exc, ValueError) else 'Native SBOM file operation failed'}
    print(json.dumps(result, sort_keys=True))
    return 0 if result['ok'] else 1

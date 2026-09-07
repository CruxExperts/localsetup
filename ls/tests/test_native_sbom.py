"""Native SBOM boundaries use synthetic bytes, never execute a native payload."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

import pytest

from ls.core.agent import native_bundle as native
from ls.core.agent import native_sbom as sbom
from ls.tests.test_native_bundle import bundle


@pytest.fixture
def authenticated(bundle, monkeypatch):
    # Loader-shaped synthetic fixtures are not genuine license/provenance evidence.
    monkeypatch.setattr(sbom, 'LICENSE_HASHES', {
        'bubblewrap-COPYING': hashlib.sha256(b'license').hexdigest(),
        'libcap-copyright': hashlib.sha256(b'copyright').hexdigest(),
    })
    return bundle()


def properties(component):
    return {row['name']: row['value'] for row in component['properties']}


def test_deterministic_inventory_input_scope_and_static_relationship(authenticated, tmp_path):
    path, digest = authenticated
    first = sbom.encode(path, digest)
    assert first == sbom.encode(path, digest)
    assert str(tmp_path).encode() not in first
    data = json.loads(first)
    subject = data['metadata']['component']
    assert subject['hashes'] == [{'alg': 'SHA-256', 'content': digest}]
    with zipfile.ZipFile(path) as archive:
        assert set(archive.namelist()) == {*native.FILES, 'manifest.json'}
        for name in archive.namelist():
            assert properties(subject)['localsetup:native:entry-sha256:' + name] == hashlib.sha256(archive.read(name)).hexdigest()
    bubble, cap = data['components']
    assert [bubble['name'], cap['name']] == ['bubblewrap', 'libcap']
    assert properties(bubble)['localsetup:native:source-input-sha256'] == native.COMPONENTS['bubblewrap']['source_sha256']
    assert properties(cap)['localsetup:native:build-input-sha256'] == native.COMPONENTS['libcap']['artifact_sha256']
    assert properties(cap)['localsetup:native:build-input-purl'] == 'pkg:deb/ubuntu/libcap-dev@1%3A2.66-5ubuntu2.4?arch=amd64'
    assert properties(cap)['localsetup:native:build-input-version'] == '1:2.66-5ubuntu2.4'
    assert cap['version'] == native.COMPONENTS['libcap']['version'] == '2.66-5ubuntu2.4'
    assert 'hashes' not in cap  # The .deb digest is not a linked-library/output hash.
    assert properties(cap)['localsetup:native:linkage'] == 'static'
    assert data['dependencies'][1] == {'ref': bubble['bom-ref'], 'dependsOn': [cap['bom-ref']]}
    assert properties(subject)['localsetup:native:host-requirement:minimum_libc'] == '2.39'
    output = tmp_path / 'sidecar.json'
    output.write_bytes(first)
    assert sbom.verify(path, digest, output)['ok']


@pytest.mark.parametrize('change', [
    lambda d: d['components'].pop(),
    lambda d: d['components'].append({'type': 'library', 'name': 'glibc'}),
    lambda d: d['components'][0].update(version='wrong'),
    lambda d: d['components'][0]['hashes'][0].update(content='0' * 64),
    lambda d: d['components'][0].update(licenses=[{'expression': 'MIT'}]),
    lambda d: d['components'][1].update(purl='pkg:generic/other@1'),
    lambda d: d['metadata']['component']['properties'].append({'name': 'extra', 'value': 'host'}),
    lambda d: d['metadata']['component']['hashes'][0].update(content='0' * 64),
    lambda d: d['dependencies'][1].update(dependsOn=[]),
    lambda d: d.update(version=True),
    lambda d: d.update(version=1.0),
])
def test_exact_records_reject_tamper(authenticated, tmp_path, change):
    path, digest = authenticated
    document = sbom.document(path, digest)
    change(document)
    sidecar = tmp_path / 'tampered.json'
    sidecar.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='differs'):
        sbom.verify(path, digest, sidecar)


@pytest.mark.parametrize('raw', [b'{}', b'{"x":1,"x":2}', b'NaN', b'\xff', b'x' * (sbom.MAX_SBOM_BYTES + 1)])
def test_invalid_sidecar_refuses(authenticated, tmp_path, raw):
    path, digest = authenticated
    sidecar = tmp_path / 'invalid.json'
    sidecar.write_bytes(raw)
    with pytest.raises(ValueError):
        sbom.verify(path, digest, sidecar)


def test_static_inspection_preserves_default_runtime_platform_guard(authenticated, monkeypatch):
    path, digest = authenticated
    def unsupported():
        raise ValueError('unsupported platform')
    monkeypatch.setattr(native, '_platform', unsupported)
    assert sbom.document(path, digest)['bomFormat'] == 'CycloneDX'
    with pytest.raises(ValueError, match='unsupported platform'):
        native.read(path, digest)


def test_emit_validates_before_output_and_never_overwrites(authenticated, tmp_path, capsys):
    path, digest = authenticated
    output = tmp_path / 'native.cdx.json'
    args = ['emit', '--bundle', str(path), '--sha256', digest, '--out', str(output)]
    assert sbom.main(args) == 0
    original = output.read_bytes()
    assert sbom.main(args) == 1
    assert output.read_bytes() == original
    assert sbom.main(['verify', '--bundle', str(path), '--sha256', digest, '--sbom', str(output)]) == 0
    output.unlink()
    path.write_bytes(b'invalid')
    assert sbom.main(args) == 1 and not output.exists()
    capsys.readouterr()


def test_changed_license_and_manifest_rejected_before_output(bundle, authenticated, tmp_path, capsys):
    def wrong_license(contents):
        contents['libcap-copyright'] = b'other license'
        manifest = json.loads(contents['manifest.json'])
        manifest['files']['libcap-copyright'] = hashlib.sha256(contents['libcap-copyright']).hexdigest()
        contents['manifest.json'] = json.dumps(manifest).encode()
    path, digest = bundle(wrong_license)
    output = tmp_path / 'absent.json'
    assert sbom.main(['emit', '--bundle', str(path), '--sha256', digest, '--out', str(output)]) == 1
    assert 'license notice' in capsys.readouterr().out
    assert not output.exists()
    with pytest.raises(ValueError):
        sbom.document(path, '0' * 64)


def test_public_entrypoint_refuses_invalid_bundle_without_output(tmp_path):
    path = tmp_path / 'bad.zip'
    path.write_bytes(b'invalid')
    output = tmp_path / 'absent.json'
    entry = Path(__file__).resolve().parents[1] / 'tools/native_sbom.py'
    result = subprocess.run([sys.executable, str(entry), 'emit', '--bundle', str(path),
                             '--sha256', '0' * 64, '--out', str(output)], capture_output=True, text=True)
    assert result.returncode == 1 and json.loads(result.stdout)['ok'] is False
    assert not output.exists()


@pytest.mark.parametrize('field,value', [('version', 'other'), ('target', 'aarch64'), ('license', '0' * 64)])
def test_unsupported_bundle_records_never_create_sidecar(bundle, authenticated, tmp_path, field, value, capsys):
    def change(contents):
        manifest = json.loads(contents['manifest.json'])
        if field == 'version':
            manifest['components']['bubblewrap']['version'] = value
        elif field == 'target':
            manifest['target']['machine'] = value
        else:
            manifest['files']['bubblewrap-COPYING'] = value
        contents['manifest.json'] = json.dumps(manifest).encode()
    path, digest = bundle(change)
    output = tmp_path / 'absent.json'
    assert sbom.main(['emit', '--bundle', str(path), '--sha256', digest, '--out', str(output)]) == 1
    assert not output.exists()
    capsys.readouterr()


@pytest.mark.parametrize('location,key', [('subject', 'host-requirement:minimum_libc'),
                                         ('libcap', 'linkage'), ('libcap', 'build-input-sha256')])
def test_altered_target_linkage_and_input_scope_rejected(authenticated, tmp_path, location, key):
    path, digest = authenticated
    document = sbom.document(path, digest)
    component = document['metadata']['component'] if location == 'subject' else document['components'][1]
    next(row for row in component['properties'] if row['name'] == 'localsetup:native:' + key)['value'] = 'wrong'
    sidecar = tmp_path / 'changed.json'
    sidecar.write_text(json.dumps(document))
    with pytest.raises(ValueError, match='differs'):
        sbom.verify(path, digest, sidecar)

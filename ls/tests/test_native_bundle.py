import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest

from ls.core.agent import native_bundle as native
from ls.core.agent import runtime_install as runtime
from ls.tests.test_runtime_install import installation


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(native, '_platform', lambda: None)
    files = {'bwrap': b'\x7fELF\x02\x01fixture', 'bubblewrap-COPYING': b'license', 'libcap-copyright': b'copyright'}
    manifest = dict(schema_version=1, target=native.TARGET, components=native.COMPONENTS,
                    files={k: hashlib.sha256(v).hexdigest() for k, v in files.items()})
    def build(change=None):
        contents = {**files, 'manifest.json': json.dumps(manifest).encode()}
        if change:
            change(contents)
        path = tmp_path / 'native.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            for name, value in contents.items():
                archive.writestr(name, value)
        return path, hashlib.sha256(path.read_bytes()).hexdigest()
    return build


def test_bundle_exact_inventory_and_materialization(bundle, tmp_path):
    path, digest = bundle()
    contents = native.read(path, digest)
    release = tmp_path / 'release'
    (release / 'venv').mkdir(parents=True)
    native.materialize(release, contents)
    for name, data in contents.items():
        installed = release / 'venv/lscli-native' / name
        assert installed.read_bytes() == data
        assert stat.S_IMODE(installed.stat().st_mode) == (0o700 if name == 'bwrap' else 0o600)
    with pytest.raises(FileExistsError):
        native.materialize(release, contents)


@pytest.mark.parametrize('change', [
    lambda c: c.update({'../escape': b'x'}),
    lambda c: c.pop('libcap-copyright'),
    lambda c: c.update(bwrap=b'changed'),
    lambda c: c.update({'manifest.json': b'{"schema_version":1,"schema_version":1}'}),
    lambda c: c.update({'manifest.json': json.dumps({'schema_version': True}).encode()}),
    lambda c: c.update({'manifest.json': b'[]'}),
])
def test_rejects_inventory_manifest_and_payload_changes(bundle, change):
    path, digest = bundle(change)
    with pytest.raises(ValueError):
        native.read(path, digest)


def test_outer_digest_symlink_and_archive_type(bundle, tmp_path):
    path, digest = bundle()
    with pytest.raises(ValueError, match='digest'):
        native.read(path, '0' * 64)
    link = tmp_path / 'link.zip'
    link.symlink_to(path)
    with pytest.raises(ValueError, match='symlink'):
        native.read(link, digest)
    with zipfile.ZipFile(path, 'a') as archive:
        entry = zipfile.ZipInfo('extra')
        entry.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(entry, 'outside')
    with pytest.raises(ValueError, match='inventory'):
        native.read(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_platform_refuses_unsupported_libc(monkeypatch):
    monkeypatch.setattr(native.sys, 'platform', 'linux')
    monkeypatch.setattr(native.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(native.platform, 'libc_ver', lambda: ('glibc', '2.38'))
    with pytest.raises(ValueError, match='glibc'):
        native._platform()
    monkeypatch.setattr(native.platform, 'libc_ver', lambda: ('glibc', '2.39'))
    native._platform()


def test_native_runtime_identity_integrity_and_recovery(installation, bundle, monkeypatch):
    original_plan = runtime.plan
    path, digest = bundle()
    def plan(*args, **kwargs):
        result = original_plan(*args)
        if kwargs:
            native.read(kwargs['sandbox_bundle'], kwargs['sandbox_sha256'])
            result['sha256'] = native.identity(args[2], kwargs['sandbox_sha256'])
        return result
    monkeypatch.setattr(runtime, 'plan', plan)
    legacy = runtime.install(*installation)
    result = runtime.install(*installation, sandbox_bundle=path, sandbox_sha256=digest)
    assert result['sha256'] != legacy['sha256']
    assert result['wheel_sha256'] == legacy['sha256']
    assert result['sandbox_sha256'] == digest
    assert result['previous'] == legacy['sha256']
    root = installation[0]
    with runtime.selected(root) as release:
        assert (release / 'venv/lscli-native/bwrap').read_bytes().startswith(b'\x7fELF')
    runtime.reselect(root, legacy['sha256'])
    runtime.reselect(root, result['sha256'])
    (release / 'venv/lscli-native/libcap-copyright').write_text('altered')
    with pytest.raises(ValueError):
        with runtime.selected(root):
            pass
    runtime.reselect(root, legacy['sha256'])
    with pytest.raises(ValueError):
        runtime.reselect(root, result['sha256'])
    assert json.loads((root / 'current.json').read_text()) == legacy


def test_real_plan_native_binding_is_read_only(bundle, tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'inspect_artifact', lambda path: None)
    wheel = tmp_path / 'localsetup.whl'
    with zipfile.ZipFile(wheel, 'w') as archive:
        archive.writestr('localsetup.dist-info/METADATA', 'Name: localsetup\nVersion: 4.4.1\n')
    root, workspace, wheelhouse = (tmp_path / n for n in ('runtime', 'workspace', 'wheelhouse'))
    workspace.mkdir()
    wheelhouse.mkdir()
    path, digest = bundle()
    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    result = runtime.plan(root, wheel, wheel_digest, wheelhouse, workspace,
                          sandbox_bundle=path, sandbox_sha256=digest)
    assert result['sha256'] == native.identity(wheel_digest, digest)
    assert result['release'] == str(root / result['sha256'])
    assert not root.exists()
    with pytest.raises(ValueError, match='together'):
        runtime.plan(root, wheel, wheel_digest, wheelhouse, workspace, sandbox_bundle=path)


def test_rejects_symlink_entry_and_compressed_expansion(bundle, monkeypatch):
    path, digest = bundle()
    with zipfile.ZipFile(path) as archive:
        contents = {x.filename: archive.read(x) for x in archive.infolist()}
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in contents.items():
            entry = zipfile.ZipInfo(name)
            entry.external_attr = ((stat.S_IFLNK if name == 'bwrap' else stat.S_IFREG) | 0o600) << 16
            archive.writestr(entry, data)
    with pytest.raises(ValueError, match='regular'):
        native.read(path, hashlib.sha256(path.read_bytes()).hexdigest())
    contents['bwrap'] = b'x' * 10000
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in contents.items():
            archive.writestr(name, data)
    monkeypatch.setattr(native, 'MAX_BYTES', 4096)
    assert path.stat().st_size < 4096
    with pytest.raises(ValueError, match='bounded'):
        native.read(path, hashlib.sha256(path.read_bytes()).hexdigest())

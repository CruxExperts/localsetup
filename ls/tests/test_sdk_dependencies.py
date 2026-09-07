from pathlib import Path

import pytest

from ls.core.sdk_payload import dependencies

ROOT = Path(__file__).resolve().parents[2]


def test_canonical_exports_preserve_scopes_markers_and_hashes():
    exported = dependencies.exports(ROOT)
    assert dependencies.refresh(ROOT, check=True) == []
    runtime = exported['sdk-runtime.lock'].decode()
    build = exported['sdk-build.lock'].decode()
    assert "httpx2-jsfetch==1.0 ; sys_platform == 'emscripten'" in runtime
    assert 'pytest==' not in runtime and 'setuptools==' not in runtime
    assert {line.split('==')[0] for line in build.splitlines() if '==' in line} == {'packaging', 'setuptools', 'wheel'}
    assert all('--hash=sha256:' in text for text in (runtime, build))


def test_check_detects_missing_changed_and_extra_text_without_writing(tmp_path, monkeypatch):
    expected = {'sdk-runtime.lock': b'a==1 --hash=sha256:abc\n', 'sdk-build.lock': b'b==2 --hash=sha256:def\n'}
    monkeypatch.setattr(dependencies, 'exports', lambda root: dict(expected))
    monkeypatch.setattr(dependencies, 'receipt', lambda root, exports: b'receipt')
    directory = tmp_path / 'ls/config'
    directory.mkdir(parents=True)
    assert sorted(dependencies.refresh(tmp_path, check=True)) == sorted([*expected, dependencies.RECEIPT])
    assert list(directory.iterdir()) == []
    dependencies.refresh(tmp_path, check=False)
    path = directory / 'sdk-runtime.lock'
    changed = path.read_bytes() + b'extra==3\n'
    path.write_bytes(changed)
    assert dependencies.refresh(tmp_path, check=True) == [path.name]
    assert path.read_bytes() == changed
    dependencies.refresh(tmp_path, check=False)
    assert dependencies.refresh(tmp_path, check=True) == []


def test_refuse_link_before_writing_either_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(dependencies, 'exports', lambda root: {'sdk-runtime.lock': b'new', 'sdk-build.lock': b'new'})
    monkeypatch.setattr(dependencies, 'receipt', lambda root, exports: b'receipt')
    directory = tmp_path / 'ls/config'
    directory.mkdir(parents=True)
    runtime = directory / 'sdk-runtime.lock'
    runtime.write_bytes(b'keep')
    (directory / 'sdk-build.lock').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='regular file'):
        dependencies.refresh(tmp_path, check=False)
    assert runtime.read_bytes() == b'keep'


@pytest.mark.parametrize("mutation", ["source", "lock", "missing", "version"])
def test_build_receipt_detects_drift_but_allows_release_version(tmp_path, mutation):
    from ls.core.sdk_payload.dependency_integrity import LOCKS, RECEIPT, receipt, verify
    (tmp_path / 'ls/config').mkdir(parents=True)
    (tmp_path / 'pyproject.toml').write_text('[project]\nversion="1.0"\ndependencies=["a==1"]\n')
    (tmp_path / 'uv.lock').write_text('[[package]]\nname="example"\nversion="1.0"\nsource={editable="."}\n')
    values = {name: b'a==1' for name in LOCKS}
    for name, data in values.items():
        (tmp_path / 'ls/config' / name).write_bytes(data)
    target = tmp_path / 'ls/config' / RECEIPT
    target.write_bytes(receipt(tmp_path, values))
    verify(tmp_path)
    if mutation == 'source':
        (tmp_path / 'pyproject.toml').write_text('[project]\ndependencies=["a==2"]\n')
    elif mutation == 'lock':
        (tmp_path / 'ls/config' / LOCKS[0]).write_bytes(b'a==2')
    elif mutation == 'missing':
        target.unlink()
    else:
        for name in ['pyproject.toml', 'uv.lock']:
            path = tmp_path / name
            path.write_text(path.read_text().replace('1.0', '2.0'))
        verify(tmp_path)
        return
    with pytest.raises(ValueError):
        verify(tmp_path)

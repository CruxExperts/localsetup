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
    monkeypatch.setattr(dependencies, 'exports', lambda root: expected)
    directory = tmp_path / 'ls/config'
    directory.mkdir(parents=True)
    assert sorted(dependencies.refresh(tmp_path, check=True)) == sorted(expected)
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
    directory = tmp_path / 'ls/config'
    directory.mkdir(parents=True)
    runtime = directory / 'sdk-runtime.lock'
    runtime.write_bytes(b'keep')
    (directory / 'sdk-build.lock').symlink_to(tmp_path / 'outside')
    with pytest.raises(ValueError, match='regular file'):
        dependencies.refresh(tmp_path, check=False)
    assert runtime.read_bytes() == b'keep'

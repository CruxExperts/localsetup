import os

import pytest

from ls.core.agent import runtime_integrity as integrity


@pytest.fixture
def sealed(tmp_path, synthetic_runtime_interpreter):
    root = tmp_path / 'venv'
    root.mkdir(mode=0o700)
    (root / 'bin').mkdir(mode=0o700)
    (root / 'bin/python').symlink_to(synthetic_runtime_interpreter)
    (root / 'fixture').write_bytes(b'qualified')
    (root / 'fixture').chmod(0o600)
    return tmp_path, integrity.seal(tmp_path)


def test_intact_environment_verifies(sealed):
    integrity.verify(*sealed)


@pytest.mark.parametrize('mutation', ['content', 'extra', 'mode', 'link', 'hardlink', 'root_mode', 'inventory'])
def test_changed_environment_is_refused(sealed, mutation):
    release, digest = sealed
    root = release / 'venv'
    file = root / 'fixture'
    if mutation == 'content':
        file.write_bytes(b'changed')
    elif mutation == 'extra':
        (root / 'unexpected.py').write_text('pass')
    elif mutation == 'mode':
        file.chmod(0o700)
    elif mutation == 'root_mode':
        root.chmod(0o777)
    elif mutation == 'link':
        (root / 'bin/python').unlink()
        (root / 'bin/python').symlink_to('/unexpected/python')
    elif mutation == 'hardlink':
        os.link(file, release / 'external-alias')
    else:
        (release / integrity.INVENTORY).write_text('{}')
    with pytest.raises(ValueError):
        integrity.verify(release, digest)


def test_host_interpreter_bytes_are_bound(tmp_path, monkeypatch):
    interpreter = tmp_path / 'host-python'
    interpreter.write_bytes(b'host executable')
    interpreter.chmod(0o700)
    monkeypatch.setattr(integrity.sys, 'executable', str(interpreter))
    (tmp_path / 'venv').mkdir(mode=0o700)
    digest = integrity.seal(tmp_path)
    interpreter.write_bytes(b'changed host executable')
    with pytest.raises(ValueError, match='changed'):
        integrity.verify(tmp_path, digest)


@pytest.mark.parametrize('mode', [0o720, 0o702, 0o777])
def test_unsafe_host_interpreter_permissions_are_refused(tmp_path, synthetic_runtime_interpreter, mode):
    (tmp_path / 'venv').mkdir(mode=0o700)
    synthetic_runtime_interpreter.chmod(mode)
    with pytest.raises(ValueError, match='Host interpreter'):
        integrity.seal(tmp_path)
    assert not (tmp_path / integrity.INVENTORY).exists()

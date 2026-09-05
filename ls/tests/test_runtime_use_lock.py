import os
from pathlib import Path

import pytest

from ls.core.agent.runtime_lock import LOCK_NAME, runtime_use


def test_readers_coexist_and_writer_waits(tmp_path):
    with runtime_use(tmp_path, timeout=0):
        with runtime_use(tmp_path, timeout=0):
            with pytest.raises(TimeoutError):
                with runtime_use(tmp_path, exclusive=True, timeout=0.01):
                    pytest.fail('writer entered')
    with runtime_use(tmp_path, exclusive=True, timeout=0):
        with pytest.raises(TimeoutError):
            with runtime_use(tmp_path, timeout=0):
                pytest.fail('reader entered')


def test_exception_releases_same_lock_inode(tmp_path):
    with pytest.raises(OSError, match='operation failed'):
        with runtime_use(tmp_path, exclusive=True):
            inode = (tmp_path / LOCK_NAME).stat().st_ino
            raise OSError('operation failed')
    with runtime_use(tmp_path, exclusive=True, timeout=0):
        assert (tmp_path / LOCK_NAME).stat().st_ino == inode


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'public', 'directory'])
def test_unsafe_lock_files_are_rejected(tmp_path, kind):
    target = tmp_path / LOCK_NAME
    other = tmp_path / 'other'
    other.write_text('preserve')
    if kind == 'symlink':
        target.symlink_to(other)
    elif kind == 'hardlink':
        os.link(other, target)
    elif kind == 'public':
        target.write_text('preserve')
        target.chmod(0o644)
    else:
        target.mkdir()
    with pytest.raises((OSError, ValueError)):
        with runtime_use(tmp_path, timeout=0):
            pytest.fail('unsafe lease entered')
    assert other.read_text() == 'preserve'


def test_symlink_parent_and_writable_root_rejected(tmp_path):
    real = tmp_path / 'real'
    real.mkdir()
    link = tmp_path / 'link'
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(OSError):
        with runtime_use(link):
            pytest.fail('symlink accepted')
    real.chmod(0o777)
    with pytest.raises(ValueError):
        with runtime_use(real):
            pytest.fail('writable root accepted')


@pytest.mark.parametrize('timeout', [-1, float('nan'), float('inf')])
def test_invalid_deadlines_do_not_create_lock(tmp_path, timeout):
    with pytest.raises(ValueError):
        with runtime_use(tmp_path, timeout=timeout):
            pytest.fail('invalid timeout accepted')
    assert not (tmp_path / LOCK_NAME).exists()


def test_process_exit_releases_exclusive_lease(tmp_path):
    import subprocess
    import sys
    code = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from ls.core.agent.runtime_lock import runtime_use
with runtime_use(Path(sys.argv[2]), exclusive=True):
    print("ready", flush=True)
    sys.stdin.readline()
'''
    root = Path(__file__).resolve().parents[2]
    child = subprocess.Popen([sys.executable, '-I', '-c', code, str(root), str(tmp_path)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        import selectors
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            assert selector.select(timeout=5), 'child failed to acquire lease'
        assert child.stdout.readline() == 'ready\n'
        with pytest.raises(TimeoutError):
            with runtime_use(tmp_path, timeout=0):
                pytest.fail('child lease bypassed')
        child.terminate()
        child.wait(timeout=5)
        with runtime_use(tmp_path, exclusive=True, timeout=0):
            pass
    finally:
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()

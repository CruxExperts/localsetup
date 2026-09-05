from contextlib import contextmanager
import os
from pathlib import Path
import time

import pytest

from ls.core.agent import sandbox


@pytest.fixture
def invocation(tmp_path, monkeypatch):
    root = tmp_path / 'runtimes'
    release = root / 'release'
    binary = release / 'venv/lscli-native/bwrap'
    binary.parent.mkdir(parents=True)
    binary.write_text('fixture')
    binary.chmod(0o700)
    stage = tmp_path / 'snapshot'
    stage.mkdir(mode=0o700)
    held = []
    @contextmanager
    def selected(path, **kwargs):
        assert path == root
        held.append(True)
        try:
            yield release
        finally:
            held.pop()
    monkeypatch.setattr(sandbox, 'selected', selected)
    monkeypatch.setattr(sandbox, '_platform', lambda: None)
    grant = sandbox.ProcessGrant('task', 'session', stage, ('/usr/bin/python3', '-c', 'print(1)'), time.monotonic()+30)
    return root, grant, held, binary


def test_invocation_keeps_lease_and_exact_authorized_command(invocation):
    root, grant, held, binary = invocation
    with sandbox.invocation(root, grant, task='task', session='session') as launch:
        command = list(launch.command)
        assert launch.cwd == binary.parents[2]
        assert dict(launch.environment) == {'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}
        with pytest.raises(TypeError):
            launch.environment['LD_PRELOAD'] = 'untrusted'
        assert held
        assert command[0] == str(binary)
        assert command[command.index('--')+1:] == list(grant.command)
        assert all(x in command for x in ('--unshare-all', '--unshare-user', '--disable-userns'))
        assert '--clearenv' in command
        assert command.count('--bind') == 1
        assert command[command.index('--bind')+1:command.index('--bind')+3] == [str(grant.staging), '/work']
        assert str(root) not in command[1:]
        assert not grant.disclose_output
    assert not held


@pytest.mark.parametrize('name', ['.git', '.env', '.env.secret', 'AGENTS.md', '.agents'])
def test_protected_snapshot_entries_refused(invocation, name):
    root, grant, _, _ = invocation
    (grant.staging / name).write_text('private')
    with pytest.raises(ValueError, match='protected'):
        with sandbox.invocation(root, grant, task='task', session='session'):
            pytest.fail('must refuse before spawn')


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'fifo', 'shared_mode'])
def test_unsafe_snapshot_entries_refused(invocation, kind):
    root, grant, _, _ = invocation
    entry = grant.staging / 'entry'
    if kind == 'symlink':
        entry.symlink_to('/etc/passwd')
    elif kind == 'hardlink':
        other = grant.staging / 'other'
        other.write_text('x')
        os.link(other, entry)
    elif kind == 'fifo':
        os.mkfifo(entry)
    else:
        entry.write_text('x')
        entry.chmod(0o666)
    with pytest.raises(ValueError, match='regular'):
        with sandbox.invocation(root, grant, task='task', session='session'):
            pytest.fail('must refuse before spawn')


def test_revocation_mismatch_and_missing_backend(invocation):
    root, grant, _, binary = invocation
    with pytest.raises(PermissionError):
        with sandbox.invocation(root, grant, task='other', session='session'):
            pass
    binary.unlink()
    with pytest.raises(RuntimeError, match='sealed'):
        with sandbox.invocation(root, grant, task='task', session='session'):
            pass
    grant.revoked.set()
    with pytest.raises(PermissionError):
        with sandbox.invocation(root, grant, task='task', session='session'):
            pass


@pytest.mark.parametrize('command', [('/bin/sh',), ('/usr/bin/../bin/sh',), ('/usr/bin/sh', '\x00'), ['/usr/bin/sh'], ()])
def test_exact_system_command_contract(tmp_path, command):
    with pytest.raises(ValueError):
        sandbox.ProcessGrant('task', 'session', tmp_path, command, time.monotonic()+1)


def test_runtime_under_exposed_system_tree_is_refused(monkeypatch):
    monkeypatch.setattr(Path, 'resolve', lambda self, **kwargs: self)
    for root in (Path('/usr/local/runtimes'), Path('/usr'), Path('/')):
        with pytest.raises(ValueError, match='outside'):
            sandbox._system_boundary(root)
    sandbox._system_boundary(Path('/private/runtimes'))

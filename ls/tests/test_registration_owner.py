from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from ls.core.agent import registration_owner as owner, registration_plan
from ls.core.agent.runtime_lock import runtime_use


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    root = tmp_path / 'runtime'
    digest = 'a' * 64
    release = root / digest
    module = release / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/ls/core/agent/registered_cli.py'
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(owner.__file__).with_name('registered_cli.py').read_bytes())
    @contextmanager
    def selected(actual, **kwargs):
        assert actual == root
        yield release
    monkeypatch.setattr(owner, 'selected', selected)
    monkeypatch.setattr(registration_plan, 'selected', selected)
    return root


def test_fresh_publish_receipt_and_modified_command(tmp_path, runtime):
    directory = tmp_path / 'bin'
    spec = owner.plan(runtime, directory, path_env=str(directory))
    assert not directory.exists()
    assert owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))['status'] == 'registered'
    target = directory / owner.CLI_COMMAND
    assert target.read_text() == spec['launcher']
    assert target.stat().st_mode & 0o777 == 0o700
    assert owner.status(directory)['status'] == 'registered'
    assert (directory / owner.RECEIPT).stat().st_mode & 0o777 == 0o600
    target.write_text('custom edit')
    assert owner.status(directory)['status'] == 'modified'
    with pytest.raises(FileExistsError):
        owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    assert target.read_text() == 'custom edit'


@pytest.mark.parametrize('phase', ['launcher', 'receipt'])
def test_interrupted_publication_is_never_replayed(tmp_path, runtime, monkeypatch, phase):
    directory = tmp_path / 'bin'
    spec = owner.plan(runtime, directory, path_env=str(directory))
    publish = owner._publish
    stop = owner.CLI_COMMAND if phase == 'launcher' else owner.RECEIPT
    def interrupted(fd, name, data, mode):
        if name == stop:
            raise OSError('simulated interruption')
        publish(fd, name, data, mode)
    monkeypatch.setattr(owner, '_publish', interrupted)
    with pytest.raises(OSError):
        owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    assert owner.status(directory) == {'status': 'incomplete'}
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    with pytest.raises(FileExistsError):
        owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    assert before == {p.name: p.read_bytes() for p in directory.iterdir()}


def test_changed_plan_and_off_path_never_create_bin(tmp_path, runtime):
    directory = tmp_path / 'bin'
    spec = owner.plan(runtime, directory, path_env=str(directory))
    with pytest.raises(ValueError):
        owner.apply(runtime, directory, '0' * 64, path_env=str(directory))
    with pytest.raises(ValueError):
        owner.apply(runtime, directory, spec['plan_sha256'], path_env='/usr/bin')
    assert not directory.exists()


def test_bin_lease_excludes_publication(tmp_path, runtime):
    directory = tmp_path / 'bin'
    directory.mkdir(mode=0o700)
    spec = owner.plan(runtime, directory, path_env=str(directory))
    with runtime_use(directory, exclusive=True):
        with pytest.raises(TimeoutError):
            owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    assert not (directory / owner.CLI_COMMAND).exists()


def test_status_without_lock_does_not_create_state(tmp_path):
    directory = tmp_path / 'bin'
    assert owner.status(directory) == {'status': 'missing'}
    directory.mkdir(mode=0o700)
    assert owner.status(directory) == {'status': 'coordination_unavailable'}
    assert list(directory.iterdir()) == []


def test_receipt_requires_typed_effective_path(tmp_path, runtime):
    import hashlib
    spec = owner.plan(runtime, tmp_path / 'bin', path_env=str(tmp_path / 'bin'))
    spec['path']['ready'] = 1
    body = dict(spec)
    body.pop('plan_sha256')
    spec['plan_sha256'] = hashlib.sha256(owner.encode(body)).hexdigest()
    with pytest.raises(ValueError, match='path specification'):
        owner._record(owner.encode({'schema_version': 1, 'specification': spec}), Path(spec['target']))


def test_owned_command_reports_reselection_as_stale(tmp_path, runtime, monkeypatch):
    directory = tmp_path / 'bin'
    spec = owner.plan(runtime, directory, path_env=str(directory))
    owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    before = (directory / owner.CLI_COMMAND).read_bytes()
    @contextmanager
    def changed_selection(root, **kwargs):
        yield root / ('b' * 64)
    monkeypatch.setattr(owner, 'selected', changed_selection)
    assert owner.status(directory) == {'status': 'stale', 'release': 'a' * 64}
    assert (directory / owner.CLI_COMMAND).read_bytes() == before

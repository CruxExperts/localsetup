from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from ls.core.agent import registration_owner as owner, registration_plan, registration_refresh as refresh
from ls.tests.test_registration_owner import runtime


@pytest.fixture
def registered(tmp_path, runtime, monkeypatch):
    directory = tmp_path / 'bin'
    selected = ['a' * 64]
    @contextmanager
    def selection(root, **kwargs):
        assert root == runtime
        yield runtime / selected[0]
    for module in (owner, registration_plan, refresh):
        monkeypatch.setattr(module, 'selected', selection)
    spec = owner.plan(runtime, directory, path_env=str(directory))
    owner.apply(runtime, directory, spec['plan_sha256'], path_env=str(directory))
    module = runtime / ('b' * 64) / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/ls/core/agent/registered_cli.py'
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(owner.__file__).with_name('registered_cli.py').read_bytes())
    selected[0] = 'b' * 64
    return directory, selected


def test_refresh_retains_recovery_receipt_and_changes_only_owned_files(registered):
    directory, selected = registered
    (directory / 'custom').write_text('keep')
    prior = (directory / owner.RECEIPT).read_bytes()
    planned = refresh.plan(directory, path_env=str(directory))
    assert owner.status(directory)['status'] == 'stale'
    refresh.apply(directory, planned['plan_sha256'], path_env=str(directory))
    assert owner.status(directory)['status'] == 'registered'
    assert (directory / 'custom').read_text() == 'keep'
    backups = list(directory.glob('.lscli-registration.previous-*.json'))
    assert len(backups) == 1 and backups[0].read_bytes() == prior
    assert not (directory / owner.PENDING).exists()


@pytest.mark.parametrize('stop', [owner.CLI_COMMAND, owner.RECEIPT])
def test_interrupted_refresh_requires_new_observed_recovery_plan(registered, monkeypatch, stop):
    directory, selected = registered
    planned = refresh.plan(directory, path_env=str(directory))
    replace = refresh._replace
    def interrupted(fd, name, *args):
        if name == stop:
            raise OSError('interrupted')
        return replace(fd, name, *args)
    monkeypatch.setattr(refresh, '_replace', interrupted)
    with pytest.raises(OSError):
        refresh.apply(directory, planned['plan_sha256'], path_env=str(directory))
    assert owner.status(directory)['status'] == 'incomplete'
    with pytest.raises(FileExistsError):
        refresh.apply(directory, planned['plan_sha256'], path_env=str(directory))
    recovery = refresh.recovery_plan(directory, path_env=str(directory))
    monkeypatch.setattr(refresh, '_replace', replace)
    with pytest.raises(ValueError):
        refresh.recover(directory, '0' * 64, path_env=str(directory))
    refresh.recover(directory, recovery['plan_sha256'], path_env=str(directory))
    assert owner.status(directory)['status'] == 'registered'


def test_custom_edit_after_recovery_plan_is_preserved(registered, monkeypatch):
    directory, selected = registered
    planned = refresh.plan(directory, path_env=str(directory))
    def interrupted(*args):
        raise OSError('interrupted')
    monkeypatch.setattr(refresh, '_finish', interrupted)
    with pytest.raises(OSError):
        refresh.apply(directory, planned['plan_sha256'], path_env=str(directory))
    recovery = refresh.recovery_plan(directory, path_env=str(directory))
    (directory / owner.CLI_COMMAND).write_text('custom edit')
    with pytest.raises(ValueError, match='unknown edits'):
        refresh.recover(directory, recovery['plan_sha256'], path_env=str(directory))
    assert (directory / owner.CLI_COMMAND).read_text() == 'custom edit'


def test_fresh_pending_can_be_explicitly_reconciled(tmp_path, runtime, monkeypatch):
    directory = tmp_path / 'bin'
    monkeypatch.setattr(refresh, 'selected', owner.selected)
    planned = owner.plan(runtime, directory, path_env=str(directory))
    publish = owner._publish
    def interrupted(fd, name, *args):
        if name == owner.CLI_COMMAND:
            raise OSError('interrupted')
        return publish(fd, name, *args)
    monkeypatch.setattr(owner, '_publish', interrupted)
    with pytest.raises(OSError):
        owner.apply(runtime, directory, planned['plan_sha256'], path_env=str(directory))
    recovery = refresh.recovery_plan(directory, path_env=str(directory))
    monkeypatch.setattr(owner, '_publish', publish)
    refresh.recover(directory, recovery['plan_sha256'], path_env=str(directory))
    assert owner.status(directory)['status'] == 'registered'


def test_modified_receipt_and_changed_selection_refuse_refresh(registered):
    directory, selected = registered
    planned = refresh.plan(directory, path_env=str(directory))
    selected[0] = 'a' * 64
    with pytest.raises(ValueError):
        refresh.apply(directory, planned['plan_sha256'], path_env=str(directory))
    selected[0] = 'b' * 64
    receipt = directory / owner.RECEIPT
    receipt.write_bytes(receipt.read_bytes() + b' ')
    with pytest.raises(ValueError, match='receipt bytes'):
        refresh.plan(directory, path_env=str(directory))
    assert not (directory / owner.PENDING).exists()

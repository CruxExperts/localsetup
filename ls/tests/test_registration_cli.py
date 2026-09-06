import json

import pytest

from ls.core.agent.cli import main
from ls.core.agent import registration_owner as owner
from ls.tests.test_registration_owner import runtime


def test_public_plan_apply_status(tmp_path, runtime, monkeypatch, capfd):
    directory = tmp_path / 'bin'
    monkeypatch.setenv('PATH', str(directory))
    options = ['--bin-dir', str(directory), '--runtime-root', str(runtime)]
    assert main(['setup', '--plan', *options]) == 0
    spec = json.loads(capfd.readouterr().out)
    assert not directory.exists()
    assert main(['setup', '--apply', *options, '--registration-sha256', spec['plan_sha256']]) == 0
    assert json.loads(capfd.readouterr().out)['status'] == 'registered'
    assert main(['setup', '--registration-status', '--bin-dir', str(directory)]) == 0
    assert json.loads(capfd.readouterr().out)['schema_version'] == 1


@pytest.mark.parametrize('options', [
    ['--apply', '--bin-dir', '/unused'],
    ['--plan', '--registration-sha256', 'a'],
    ['--plan', '--bin-dir', '/unused', '--registration-sha256', 'a'],
    ['--registration-status'],
    ['--registration-status', '--bin-dir', '/unused', '--runtime-root', '/unused'],
    ['--plan', '--bin-dir', '/unused', '--profile-input', '/unused'],
    ['--plan', '--bin-dir', '/unused', '--wheel', '/unused'],
    ['--reselect', 'a', '--bin-dir', '/unused'],
    ['--reselect', '', '--bin-dir', '/unused'],
    ['--plan', '--bin-dir', '/unused', '--sha256', ''],
    ['--registration-status', '--bin-dir', '/unused', '--timeout', '1'],
])
def test_mixed_or_incomplete_options_fail_before_owner(options, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Owner must not run after invalid options')
    monkeypatch.setattr(owner, 'plan', forbidden)
    monkeypatch.setattr(owner, 'apply', forbidden)
    monkeypatch.setattr(owner, 'status', forbidden)
    with pytest.raises(SystemExit) as exc:
        main(['setup', *options])
    assert exc.value.code == 2


def test_missing_status_and_sanitized_error(tmp_path, capfd, monkeypatch):
    directory = tmp_path / 'absent'
    assert main(['setup', '--registration-status', '--bin-dir', str(directory)]) == 3
    assert json.loads(capfd.readouterr().out)['status'] == 'missing'
    assert not directory.exists()
    def fail(*args, **kwargs):
        raise ValueError('PRIVATE_SENTINEL')
    monkeypatch.setattr(owner, 'status', fail)
    assert main(['setup', '--registration-status', '--bin-dir', str(directory)]) == 2
    captured = capfd.readouterr()
    assert not captured.out and 'PRIVATE_SENTINEL' not in captured.err

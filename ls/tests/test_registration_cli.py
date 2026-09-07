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
    ['--plan', '--refresh-registration'],
    ['--registration-status', '--bin-dir', '/unused', '--recover-registration'],
    ['--apply', '--bin-dir', '/unused', '--refresh-registration'],
    ['--plan', '--bin-dir', '/unused', '--recover-registration', '--runtime-root', '/unused'],
    ['--plan', '--bin-dir', '/unused', '--refresh-registration', '--recover-registration'],
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


def test_owned_modes_forward_recorded_root_and_reviewed_digest(tmp_path, monkeypatch, capfd):
    from ls.core.agent import registration_refresh
    calls = []
    def planned(directory):
        calls.append(('plan', directory))
        return {'plan_sha256': 'a' * 64}
    def applied(directory, digest):
        calls.append(('apply', directory, digest))
        return {'status': 'registered'}
    for name in ('plan', 'recovery_plan'):
        monkeypatch.setattr(registration_refresh, name, planned)
    for name in ('apply', 'recover'):
        monkeypatch.setattr(registration_refresh, name, applied)
    for flag in ('--refresh-registration', '--recover-registration'):
        options = ['--bin-dir', str(tmp_path), flag]
        assert main(['setup', '--plan', *options], default_runtime_root=tmp_path / 'ignored') == 0
        assert json.loads(capfd.readouterr().out)['plan_sha256'] == 'a' * 64
        assert main(['setup', '--apply', *options, '--registration-sha256', 'a' * 64]) == 0
        assert json.loads(capfd.readouterr().out)['status'] == 'registered'
    assert calls == [('plan', tmp_path), ('apply', tmp_path, 'a' * 64)] * 2

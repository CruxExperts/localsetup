from contextlib import contextmanager

import pytest

from ls.core.agent import cli, registered_cli as registered


def test_registration_releases_lease_before_dispatch_and_binds_default(tmp_path, monkeypatch):
    digest = 'a' * 64
    active = []
    @contextmanager
    def selected(root, **options):
        assert root == tmp_path and options == {'timeout': 5, 'create': False}
        active.append(True)
        yield root / digest
        active.pop()
    monkeypatch.setattr(registered, 'selected', selected)
    monkeypatch.setattr(registered, '_origin', lambda release: None)
    def dispatch(argv, *, default_runtime_root):
        assert not active
        assert argv == ['setup', '--plan'] and default_runtime_root == tmp_path
        return 17
    monkeypatch.setattr(cli, 'main', dispatch)
    assert registered.main([str(tmp_path), digest, 'setup', '--plan']) == 17


def test_stale_registration_refuses_even_setup(tmp_path, monkeypatch, capfd):
    @contextmanager
    def selected(*args, **kwargs):
        yield tmp_path / ('b' * 64)
    monkeypatch.setattr(registered, 'selected', selected)
    monkeypatch.setattr(cli, 'main', lambda *a, **k: pytest.fail('stale dispatch'))
    assert registered.main([str(tmp_path), 'a' * 64, 'setup', '--apply']) == 3
    assert 'stale' in capfd.readouterr().err


def test_source_origin_cannot_impersonate_installed_release(tmp_path):
    with pytest.raises(ValueError, match='protected installed'):
        registered._origin(tmp_path)


def test_registered_runtime_default_reaches_forwarded_run_arguments(tmp_path, monkeypatch):
    from ls.core.agent import run_cli
    class Dispatched(Exception):
        pass
    def launch(argv, args):
        assert args.runtime_root == tmp_path
        assert argv[-2:] == ['--runtime-root', str(tmp_path)]
        raise Dispatched
    monkeypatch.setattr(run_cli, 'launch', launch)
    with pytest.raises(Dispatched):
        cli.main(['run', '--profile', 'fixture', '--prompt-stdin', '--grant', 'grant.json', '--resource-parent', '/fixture'], default_runtime_root=tmp_path)


def test_registered_default_skips_profile_setup(tmp_path, monkeypatch):
    from ls.core.agent import profile_setup_cli
    def configure(args):
        assert args.runtime_root is None
        return 0
    monkeypatch.setattr(profile_setup_cli, 'main', configure)
    assert cli.main(['setup', '--plan', '--profile-input', 'input.json'], default_runtime_root=tmp_path) == 0


def test_explicit_runtime_root_remains_an_explicit_override(tmp_path, monkeypatch, capfd):
    import json
    override = tmp_path / 'explicit'
    def inspect(**options):
        assert options == {'runtime_root': override}
        return {'status': 'not_ready'}
    monkeypatch.setattr(cli, 'inspect', inspect)
    assert cli.main(['doctor', '--format', 'json', '--runtime-root', str(override)],
                    default_runtime_root=tmp_path) == 3
    assert json.loads(capfd.readouterr().out)['status'] == 'not_ready'

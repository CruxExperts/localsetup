import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ls.core.agent import profiles, trusted_profile


@pytest.fixture
def source(tmp_path):
    tmp_path.chmod(0o700)
    path = tmp_path/'profiles.json'
    path.write_text(json.dumps({'schema_version': 1, 'profiles': {'fixture': {
        'base_url': 'https://fixture.invalid/v1/', 'api': 'chat_completions',
        'model': 'fixture', 'credential_env': 'FIXTURE_KEY', 'timeout_seconds': 10,
        'capabilities': [], 'allow_loopback_http': False}}}))
    path.chmod(0o644)
    return path


def test_readable_nonsecret_configuration_is_trusted(source):
    assert profiles.load(source, 'fixture').model == 'fixture'


@pytest.mark.parametrize('target', ['file', 'parent'])
def test_other_principal_write_access_is_not_runtime_authority(source, target):
    (source if target == 'file' else source.parent).chmod(0o666 if target == 'file' else 0o777)
    try:
        with pytest.raises(ValueError, match='unsafe|write access'):
            profiles.load(source, 'fixture')
        # Inventory and reviewed setup input do not resolve credentials.
        assert 'fixture' in profiles.document(source)
    finally:
        source.parent.chmod(0o700)


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'directory'])
def test_actual_opened_inode_is_checked_without_blocking(source, monkeypatch, kind):
    original = os.open
    swapped = []
    def replace_at_open(path, flags, *args, **kwargs):
        if path == source.name and not swapped:
            swapped.append(True)
            source.unlink()
            if kind == 'symlink':source.symlink_to('/dev/null')
            elif kind == 'fifo':os.mkfifo(source, 0o600)
            else:source.mkdir(mode=0o700)
        return original(path, flags, *args, **kwargs)
    monkeypatch.setattr(trusted_profile.os, 'open', replace_at_open)
    with pytest.raises((OSError, ValueError)):
        profiles.load(source, 'fixture')
    assert swapped


def test_symlink_ancestor_is_not_followed(source):
    alias = source.parent/'alias';alias.symlink_to(source.parent, target_is_directory=True)
    with pytest.raises(ValueError):profiles.load(alias/source.name, 'fixture')


@pytest.mark.parametrize('target', ['file', 'parent'])
@pytest.mark.parametrize('uid', [0, 2147483646])
def test_owner_policy_on_opened_inode(source, monkeypatch, target, uid):
    inode = (source if target == 'file' else source.parent).stat().st_ino
    original = os.fstat
    def ownership(fd):
        info = original(fd)
        return (SimpleNamespace(st_uid=uid, st_mode=info.st_mode)
                if info.st_ino == inode else info)
    monkeypatch.setattr(trusted_profile.os, 'fstat', ownership)
    if uid == 0:assert profiles.load(source, 'fixture').model == 'fixture'
    else:
        with pytest.raises(ValueError):profiles.load(source, 'fixture')


def test_runtime_load_rejects_before_credentials(source, monkeypatch):
    from ls.core.agent import run_cli, compact_cli, completion_cli
    from argparse import Namespace
    source.chmod(0o666)
    def credential(*args):pytest.fail('Untrusted profile reached credential resolution')
    monkeypatch.setattr(profiles.Profile, 'credential', credential)
    for module in (run_cli, compact_cli):
        monkeypatch.setattr(module, 'defaults', lambda args: args)
        with pytest.raises(ValueError):module.launch([], Namespace(profiles=source, profile='fixture'))
    assert completion_cli.main(['complete', '--profile', 'fixture', '--profiles', str(source), '--request', '-']) == 3

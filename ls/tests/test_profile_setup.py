import json
import os
from pathlib import Path

import pytest

from ls.core.agent import profile_setup as setup
from ls.core.agent.profiles import document, load
from ls.tests.test_profile_inventory import configuration


def test_plan_and_create_are_explicit_private_and_nonoverwriting(tmp_path):
    source, profile = configuration(tmp_path)
    target = tmp_path / 'absent/config/profiles.json'
    planned = setup.plan(source, target)
    assert not target.parent.exists()
    assert planned['profile_count'] == 1 and planned['expected_target'] == 'absent'
    assert 'PRIVATE_CREDENTIAL_NAME' not in json.dumps(planned)
    assert setup.apply(source, target, planned['sha256'])['status'] == 'created'
    assert target.stat().st_mode & 0o777 == 0o600
    assert load(target, 'selected').model == profile['model']
    before = target.read_bytes()
    with pytest.raises(FileExistsError):
        setup.apply(source, target, planned['sha256'])
    assert target.read_bytes() == before
    assert list(target.parent.iterdir()) == [target]


def test_changed_input_digest_leaves_missing_parents_absent(tmp_path):
    source, profile = configuration(tmp_path)
    target = tmp_path / 'absent/profiles.json'
    planned = setup.plan(source, target)
    values = document(source)
    values['selected']['model'] = 'changed'
    source.write_text(json.dumps({'schema_version': 1, 'profiles': values}))
    with pytest.raises(ValueError, match='digest'):
        setup.apply(source, target, planned['sha256'])
    assert not target.parent.exists()


@pytest.mark.parametrize('kind', ['file', 'link', 'fifo', 'parent-link', 'parent-writable'])
def test_unsafe_or_existing_targets_are_preserved(tmp_path, kind):
    source, _ = configuration(tmp_path)
    target = tmp_path / 'config/result.json'
    target.parent.mkdir(mode=0o700)
    if kind == 'file':
        target.write_text('custom')
    elif kind == 'link':
        target.symlink_to(tmp_path / 'absent')
    elif kind == 'fifo':
        os.mkfifo(target)
    elif kind == 'parent-link':
        target.parent.rmdir()
        target.parent.symlink_to(tmp_path, target_is_directory=True)
    else:
        target.parent.chmod(0o777)
    with pytest.raises((OSError, ValueError)):
        setup.plan(source, target)
    assert source.exists()
    if kind == 'file':
        assert target.read_text() == 'custom'


def test_competing_creation_wins_without_overwrite(tmp_path, monkeypatch):
    source, _ = configuration(tmp_path)
    target = tmp_path / 'config/result.json'
    planned = setup.plan(source, target)
    original = os.link
    def race(*args, **kwargs):
        target.write_text('other writer')
        return original(*args, **kwargs)
    monkeypatch.setattr(os, 'link', race)
    with pytest.raises(FileExistsError):
        setup.apply(source, target, planned['sha256'])
    assert target.read_text() == 'other writer'
    assert list(target.parent.iterdir()) == [target]


def test_cli_profile_only_plan_and_apply(tmp_path, capfd):
    from ls.core.agent.cli import main
    source, _ = configuration(tmp_path)
    target = tmp_path / 'config/result.json'
    options = ['--profile-input', str(source), '--profiles', str(target)]
    assert main(['setup', '--plan', *options]) == 0
    plan = json.loads(capfd.readouterr().out)
    assert not target.exists()
    assert main(['setup', '--apply', *options, '--profile-sha256', plan['sha256']]) == 0
    assert json.loads(capfd.readouterr().out)['status'] == 'created'
    with pytest.raises(SystemExit) as exc:
        main(['setup', '--plan', *options, '--wheel', 'unexpected.whl'])
    assert exc.value.code == 2

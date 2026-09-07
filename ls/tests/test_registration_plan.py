from contextlib import contextmanager
from pathlib import Path
import shlex
import sys

import pytest

from ls.core.agent import registration_plan as registration


@pytest.fixture
def selected(tmp_path, monkeypatch):
    root = tmp_path / "runtimes with ' quote"
    release = root / ('a' * 64)
    module = release / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages/ls/core/agent/registered_cli.py'
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(registration.__file__).with_name('registered_cli.py').read_bytes())
    @contextmanager
    def select(actual, **options):
        assert actual == root and options == {'timeout': 5, 'create': False}
        yield release
    monkeypatch.setattr(registration, 'selected', select)
    return root, module


def test_plan_preserves_missing_bin_and_quotes_protected_launcher(tmp_path, selected):
    root, _ = selected
    bin_dir = tmp_path / 'space and quote\' /bin'
    result = registration.plan(root, bin_dir, path_env=str(bin_dir))
    assert not bin_dir.parent.exists()
    assert result['path']['ready'] and result['expected_target'] == 'absent'
    command = shlex.split(result['launcher'].splitlines()[1])
    assert command[:6] == ['exec', str(root / ('a' * 64) / 'venv/bin/python'), '-I', '-B', '-m', 'ls.core.agent.registered_cli']
    assert result == registration.plan(root, bin_dir, path_env=str(bin_dir))


def test_path_absence_and_shadowing_are_distinct(tmp_path, selected):
    root, _ = selected
    bin_dir = tmp_path / 'absent-bin'
    assert not registration.plan(root, bin_dir, path_env='/usr/bin')['path']['ready']
    earlier = tmp_path / 'earlier'
    earlier.mkdir()
    command = earlier / 'lscli'
    command.write_text('custom')
    command.chmod(0o700)
    with pytest.raises(FileExistsError, match='earlier PATH'):
        registration.plan(root, bin_dir, path_env=str(earlier) + ':' + str(bin_dir))
    assert registration.plan(root, bin_dir, path_env=str(bin_dir) + ':' + str(earlier))['path']['ready']
    assert command.read_text() == 'custom'


@pytest.mark.parametrize('kind', ['file', 'link'])
def test_existing_command_is_not_adopted_from_its_marker(tmp_path, selected, kind):
    root, _ = selected
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir(mode=0o700)
    target = bin_dir / 'lscli'
    if kind == 'file':
        target.write_text('# managed command\n')
    else:
        target.symlink_to(tmp_path / 'missing')
    with pytest.raises(FileExistsError):
        registration.plan(root, bin_dir, path_env=str(bin_dir))
    assert target.is_symlink() if kind == 'link' else target.read_text() == '# managed command\n'


def test_incompatible_dispatcher_is_not_executed(tmp_path, selected):
    root, module = selected
    module.write_text('raise AssertionError("must never execute")')
    with pytest.raises(ValueError, match='qualified registration dispatcher'):
        registration.plan(root, tmp_path / 'bin', path_env='/usr/bin')


def test_registration_cannot_modify_runtime_tree(selected):
    root, _ = selected
    with pytest.raises(ValueError, match='outside the protected runtime'):
        registration.plan(root, root / 'bin', path_env=str(root / 'bin'))

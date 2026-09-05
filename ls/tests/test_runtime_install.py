import hashlib
import json
from pathlib import Path

import pytest

from ls.core.agent import runtime_install as runtime


@pytest.fixture
def installation(tmp_path, monkeypatch):
    root = tmp_path / 'runtimes'
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    wheelhouse = tmp_path / 'wheels'
    wheelhouse.mkdir()
    wheel = tmp_path / 'framework.whl'
    wheel.write_bytes(b'candidate')
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    def plan(root, wheel, digest, wheelhouse, workspace):
        return dict(root=str(root), wheel=str(wheel), sha256=digest, wheelhouse=str(wheelhouse), version="1.0.0")
    monkeypatch.setattr(runtime, 'plan', plan)
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: '/trusted/uv')
    def populate(release, *args):
        (release / 'venv').mkdir(mode=0o700)
        (release / 'venv' / 'fixture').write_text('installed')
        (release / 'venv' / 'fixture').chmod(0o600)
    monkeypatch.setattr(runtime, '_populate', populate)
    return root, wheel, digest, wheelhouse, workspace


def test_install_selects_under_lease_and_blocks_upgrade(installation):
    result = runtime.install(*installation)
    root, wheel, digest, wheelhouse, workspace = installation
    assert result['sha256'] == digest and result['previous'] is None
    with runtime.selected(root) as release:
        assert release.name == digest
        with pytest.raises(TimeoutError):
            runtime.install(*installation, timeout=0.01)
    with pytest.raises(ValueError, match='already exists'):
        runtime.install(*installation)


def test_failed_upgrade_preserves_selected_release_and_incomplete_slot(installation, monkeypatch):
    runtime.install(*installation)
    root, wheel, _, wheelhouse, workspace = installation
    original = (root / 'current.json').read_bytes()
    wheel.write_bytes(b'next candidate')
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    def fail(*args):
        raise RuntimeError('injected build failure')
    monkeypatch.setattr(runtime, '_populate', fail)
    with pytest.raises(RuntimeError, match='injected'):
        runtime.install(root, wheel, digest, wheelhouse, workspace)
    assert (root / 'current.json').read_bytes() == original
    assert json.loads((root / digest / 'status.json').read_text())['status'] == 'incomplete'
    with pytest.raises(ValueError, match='already exists'):
        runtime.install(root, wheel, digest, wheelhouse, workspace)


def test_successful_upgrade_retains_previous_release(installation):
    first = runtime.install(*installation)
    root, wheel, _, wheelhouse, workspace = installation
    wheel.write_bytes(b'next candidate')
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    second = runtime.install(root, wheel, digest, wheelhouse, workspace)
    assert second['previous'] == first['sha256']
    assert (root / first['sha256'] / 'status.json').is_file()
    with runtime.selected(root) as release:
        assert release.name == digest


def test_selection_rejects_altered_completion_record(installation):
    runtime.install(*installation)
    root, _, digest, _, _ = installation
    (root / digest / 'status.json').write_text('{}')
    with pytest.raises(ValueError, match='does not match'):
        with runtime.selected(root):
            pytest.fail('altered record selected')


def test_plan_digest_failure_does_not_create_runtime(tmp_path):
    wheel = tmp_path / 'candidate.whl'
    wheel.write_bytes(b'bad')
    root = tmp_path / 'runtime'
    with pytest.raises(ValueError, match='digest'):
        runtime.plan(root, wheel, '0' * 64, tmp_path, tmp_path / 'workspace')
    assert not root.exists()


def test_plan_rejects_runtime_inside_enclosing_repository(tmp_path):
    repository = tmp_path / 'project'
    (repository / '.git').mkdir(parents=True)
    nested = repository / 'src'
    nested.mkdir()
    with pytest.raises(ValueError, match='separate trees'):
        runtime.plan(repository / 'runtime', tmp_path / 'unused.whl', '0' * 64, tmp_path, nested)
    assert not (repository / 'runtime').exists()


@pytest.mark.parametrize('error', [TypeError('malformed manifest'), RecursionError('deep manifest')])
def test_setup_normalizes_artifact_shape_errors(tmp_path, monkeypatch, capsys, error):
    from ls.core.agent.cli import main
    def invalid(*args):
        raise error
    monkeypatch.setattr(runtime, 'plan', invalid)
    assert main(['setup', '--plan', '--wheel', str(tmp_path / 'x.whl'), '--sha256', '0' * 64, '--wheelhouse', str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert not result.out and 'setup failed' in result.err


def test_install_command_timeout_reaps_child(tmp_path, monkeypatch):
    import subprocess
    import sys
    import time
    processes = []
    original = subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(runtime.subprocess, 'Popen', capture)
    with pytest.raises(subprocess.TimeoutExpired):
        runtime._run([sys.executable, '-I', '-c', 'import time; time.sleep(30)'],
                     directory=tmp_path, deadline=time.monotonic() + 0.03, environment={})
    assert len(processes) == 1 and processes[0].poll() is not None


def test_setup_cancellation_returns_terminal_status(tmp_path, monkeypatch, capsys):
    from ls.core.agent.cli import main
    def cancel(*args, **kwargs):
        raise KeyboardInterrupt
    monkeypatch.setattr(runtime, 'install', cancel)
    assert main(['setup', '--apply', '--wheel', str(tmp_path / 'x.whl'), '--sha256', '0' * 64, '--wheelhouse', str(tmp_path)]) == 130
    result = capsys.readouterr()
    assert not result.out and 'cancelled' in result.err


def test_reselect_checks_integrity_before_replacing_pointer(installation):
    first = runtime.install(*installation)
    root, wheel, _, wheelhouse, workspace = installation
    wheel.write_bytes(b'next candidate')
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    runtime.install(root, wheel, digest, wheelhouse, workspace)
    runtime.reselect(root, first['sha256'])
    before = (root / 'current.json').read_bytes()
    (root / digest / 'venv' / 'fixture').write_text('altered')
    with pytest.raises(ValueError, match='changed'):
        runtime.reselect(root, digest)
    assert (root / 'current.json').read_bytes() == before
    with runtime.selected(root) as release:
        assert release.name == first['sha256']


def test_setup_reselect_without_artifact_inputs(installation, capsys):
    from ls.core.agent.cli import main
    result = runtime.install(*installation)
    assert main(['setup', '--reselect', result['sha256'], '--runtime-root', str(installation[0])]) == 0
    assert json.loads(capsys.readouterr().out) == result


def test_reselect_expired_verification_preserves_pointer(installation, monkeypatch):
    runtime.install(*installation)
    root, _, digest, _, _ = installation
    before = (root / 'current.json').read_bytes()
    now = [100.0]
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: now[0])
    def expire(*args):
        now[0] += 2
    monkeypatch.setattr(runtime, 'verify_runtime', expire)
    with pytest.raises(TimeoutError, match='before activation'):
        runtime.reselect(root, digest, timeout=1)
    assert (root / 'current.json').read_bytes() == before


@pytest.mark.parametrize('damage', ['incomplete', 'unsealed'])
def test_reselect_refuses_unqualified_slot(installation, damage):
    runtime.install(*installation)
    root, _, digest, _, _ = installation
    pointer = (root / 'current.json').read_bytes()
    if damage == 'incomplete':
        record = json.loads((root / digest / 'status.json').read_text())
        record['status'] = 'incomplete'
        (root / digest / 'status.json').write_text(json.dumps(record))
    else:
        (root / digest / 'inventory.json').unlink()
    with pytest.raises(ValueError):
        runtime.reselect(root, digest)
    assert (root / 'current.json').read_bytes() == pointer

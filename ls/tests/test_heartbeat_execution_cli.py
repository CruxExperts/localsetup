import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from ls.core.agent import heartbeat_execution_cli as cli
from ls.core.agent import heartbeat_execution as execution
from ls.core.harness import _load_runtime
from ls.tests.test_heartbeat_accounting_cli import call
from ls.tests.test_heartbeat_execution import runtime, configured, policy, fake_dispatch

FRAMEWORK = Path(__file__).resolve().parents[2]


def options(workspace, **changes):
    return SimpleNamespace(no_agent=False, force=False, action_input=workspace.parent/'action.json',
                           accounting_root=workspace.parent/'control', expected_binding='a'*64,
                           expected_head='b'*64, **changes)


def config(workspace, text='heartbeat:\n  enabled: true\n'):
    path = workspace/'config/codex_heartbeat.yaml'
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)
    return path


def test_public_no_agent_and_disabled_skip_without_private_inputs(tmp_path):
    workspace = tmp_path/'workspace'
    workspace.mkdir(mode=0o700)
    result = call(workspace, 'run', '--action-input', tmp_path/'absent', '--no-agent')
    assert result['reason'] == 'no_agent'
    result = call(workspace, 'run', '--action-input', tmp_path/'absent')
    assert result['reason'] == 'heartbeat.disabled'
    assert list(workspace.iterdir()) == []


def test_enabled_partial_options_fail_and_never_run_hooks(tmp_path):
    workspace = tmp_path/'workspace'
    workspace.mkdir(mode=0o700)
    config(workspace, 'heartbeat:\n  enabled: true\npre_commands:\n - command: [touch, MUST_NOT_EXIST]\n')
    call(workspace, 'run', '--action-input', tmp_path/'absent', expected=2)
    assert not (workspace/'MUST_NOT_EXIST').exists()
    assert not (workspace/'.localsetup').exists()


def test_public_dispatch_holds_existing_heartbeat_lock_and_releases(tmp_path, monkeypatch):
    workspace = tmp_path/'workspace'
    workspace.mkdir(mode=0o700)
    path = config(workspace)
    runtime_module = _load_runtime(FRAMEWORK)
    state = runtime_module.state_root_from_config(workspace, {'heartbeat': {'enabled': True}})
    def dispatch(source, target, root, **kwargs):
        assert kwargs['control_paths'] == (path, state)
        lock, _ = runtime_module.acquire_lock(state, 3600)
        assert lock is None
        return dict(schema_version=1, outcome='execution_completed')
    monkeypatch.setattr(execution, 'execute', dispatch)
    result, code = cli.execute(options(workspace), workspace, FRAMEWORK)
    assert code == 0 and result['outcome'] == 'execution_completed'
    assert not (state/runtime_module.LOCK_NAME).exists()


def test_overlap_skips_dispatch_and_unsafe_existing_lock_is_preserved(tmp_path, monkeypatch):
    workspace = tmp_path/'workspace'
    workspace.mkdir(mode=0o700)
    config(workspace)
    runtime_module = _load_runtime(FRAMEWORK)
    state = runtime_module.state_root_from_config(workspace, {})
    fd = cli._parent(state/runtime_module.LOCK_NAME, create=True)
    os.close(fd)
    lock, _ = runtime_module.acquire_lock(state, 3600)
    monkeypatch.setattr(execution, 'execute', lambda *a, **k: pytest.fail('must not dispatch'))
    try:
        result, code = cli.execute(options(workspace), workspace, FRAMEWORK)
        assert code == 1 and result['outcome'] == 'locked'
    finally:
        runtime_module.release_lock(state, lock)
    original = tmp_path/'custom'
    original.write_text('preserve')
    link = state/runtime_module.LOCK_NAME
    link.symlink_to(original)
    assert cli.main(options(workspace), workspace, FRAMEWORK) == 2
    assert link.is_symlink() and original.read_text() == 'preserve'


@pytest.mark.parametrize('scope', ['.', 'config', 'config/codex_heartbeat.yaml', '.localsetup',
                                  '.localsetup/state/codex-heartbeat/nested'])
def test_captured_grant_cannot_write_control_or_state(runtime, monkeypatch, scope):
    workspace, root, source, value = runtime
    grant_path = Path(value['grant'])
    grant = json.loads(grant_path.read_text())
    grant['write'] = [scope]
    grant_path.write_text(json.dumps(grant))
    plan, state = policy(runtime)
    calls = fake_dispatch(monkeypatch, runtime)
    path = config(workspace)
    controls = (path, workspace/'.localsetup/state/codex-heartbeat')
    with pytest.raises(PermissionError, match='mutate control'):
        execution.execute(source, workspace, root, expected_binding=plan['binding'], expected_head=state['head'],
                          control_paths=controls)
    assert not calls and execution.store.inspect(root, workspace)['head'] == state['head']


def test_nonoverlapping_write_scope_remains_authorized(runtime, monkeypatch):
    workspace, root, source, value = runtime
    plan, state = policy(runtime)
    calls = fake_dispatch(monkeypatch, runtime)
    path = config(workspace)
    result = execution.execute(source, workspace, root, expected_binding=plan['binding'], expected_head=state['head'],
        control_paths=(path, workspace/'.localsetup/state/codex-heartbeat'))
    assert result['outcome'] == 'execution_completed' and calls == ['run']


def test_disabled_and_no_agent_bypass_state_and_configuration_resolution(tmp_path, monkeypatch):
    workspace = tmp_path/'workspace'
    workspace.mkdir(mode=0o700)
    config(workspace, 'heartbeat:\n  enabled: false\n  state_dir: []\n')
    args = options(workspace)
    args.action_input = None
    result, code = cli.execute(args, workspace, FRAMEWORK)
    assert code == 0 and result['reason'] == 'heartbeat.disabled'
    monkeypatch.setattr(cli, '_config', lambda _: pytest.fail('no-agent must bypass configuration'))
    args.no_agent = True
    result, code = cli.execute(args, workspace, FRAMEWORK)
    assert code == 0 and result['reason'] == 'no_agent'
    assert not (workspace/'.localsetup').exists()

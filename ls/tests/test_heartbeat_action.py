import json

import pytest

from ls.core.branding import CLI_COMMAND
from ls.core.agent import heartbeat_action as action
from ls.core.agent.registration_plan import command
from ls.tests.test_heartbeat_accounting_cli import private, call


@pytest.fixture
def configured(tmp_path, monkeypatch):
    workspace = tmp_path/'workspace'
    workspace.mkdir()
    value = dict(schema_version=1, operation='attempt1', task='task', session='session', checkpoint=None,
        profile='fixture', prompt='Private task text', run=dict(requests=2, tools=3, tokens=100, seconds=60),
        compact=None, idle_seconds=30, output_bytes=4096)
    for key in action.PATHS:
        value[key] = str(tmp_path/key)
    value['executable'] = str(tmp_path/'bin'/CLI_COMMAND)
    private(tmp_path/'grant', dict(schema_version=1, read=['.'], write=['src'], disclose=['src'], recipes={}))
    private(tmp_path/'profiles', dict(schema_version=1, profiles={'fixture':dict(
        base_url='http://127.0.0.1:9876/v1', api='responses', model='fixture', credential_env='NOT_SET',
        timeout_seconds=30, capabilities=['tools', 'streaming'], allow_loopback_http=True)}))
    source = private(tmp_path/'action.json', value)
    monkeypatch.setattr(action, 'resolve', lambda executable, root: command(root, 'e'*64))
    return workspace, tmp_path/'accounting', source, value


def test_binding_is_private_deterministic_and_charges_compaction(configured):
    workspace, root, source, value = configured
    first = action.plan(source, workspace, root)
    assert first == action.plan(source, workspace, root)
    assert not root.exists()
    assert value['prompt'] not in json.dumps(first)
    assert first['envelope']['seconds'] == 60
    value.update(checkpoint='a'*64, compact=dict(tokens=200, seconds=40, keep_messages=0, disclose_history=True))
    private(source, value)
    second = action.plan(source, workspace, root)
    assert second['binding'] != first['binding']
    assert second['envelope'] == dict(attempts=1, requests=3, tools=3, tokens=300, seconds=100, compactions=1)
    assert second['authorization']['compact'] == dict(tokens=200, seconds=40)


@pytest.mark.parametrize('change', ['prompt', 'operation', 'checkpoint', 'grant', 'profiles', 'runtime'])
def test_every_execution_input_invalidates_binding(configured, monkeypatch, change):
    workspace, root, source, value = configured
    first = action.plan(source, workspace, root)
    if change in ('grant', 'profiles'):
        from pathlib import Path
        target = Path(value[change])
        target.write_bytes(target.read_bytes()+b'\n')
    elif change == 'runtime':
        monkeypatch.setattr(action, 'resolve', lambda executable, root: command(root, 'f'*64))
    else:
        value[change] = 'b'*64 if change == 'checkpoint' else 'different'
        private(source, value)
    assert action.plan(source, workspace, root)['binding'] != first['binding']


@pytest.mark.parametrize('bad', ['workspace_input', 'public_grant', 'symlink', 'duplicate', 'overlap',
                                  'compact_without_history', 'compact_token_limit', 'phase_time', 'bool_limit'])
def test_unsafe_inputs_fail_before_runtime_resolution(configured, monkeypatch, bad):
    workspace, root, source, value = configured
    from pathlib import Path
    if bad == 'workspace_input':
        source = private(workspace/'action.json', value)
    elif bad == 'public_grant':
        Path(value['grant']).chmod(0o644)
    elif bad == 'symlink':
        link = source.with_name('link.json')
        link.symlink_to(source)
        source = link
    elif bad == 'duplicate':
        source.write_text('{"schema_version":1,"schema_version":1}')
    else:
        if bad == 'overlap':
            value['state_root'] = str(source.parent)
        elif bad.startswith('compact'):
            value['compact'] = dict(tokens=1000001 if bad == 'compact_token_limit' else 200,
                                    seconds=40, keep_messages=8, disclose_history=True)
            if bad == 'compact_token_limit': value['checkpoint'] = 'a'*64
        elif bad == 'phase_time': value['run']['seconds'] = 20
        else: value['idle_seconds'] = True
        private(source, value)
    def unexpected(*args):
        pytest.fail('Unsafe controller input reached runtime qualification')
    monkeypatch.setattr(action, 'resolve', unexpected)
    with pytest.raises((ValueError, OSError)):
        action.plan(source, workspace, root)
    assert not root.exists()


def test_public_action_plan_rejects_missing_registration_without_state(configured):
    workspace, root, source, _ = configured
    result = call(workspace, 'accounting', 'action-plan', '--input', source, '--accounting-root', root, expected=2)
    assert 'Private task text' not in result.stderr
    assert not root.exists()


def test_cli_output_initializes_real_policy_authorization(configured, capfd):
    from argparse import Namespace
    import hashlib
    from ls.core.agent import heartbeat_accounting_cli as cli, heartbeat_budget_store as store
    from ls.tests.test_heartbeat_budget_store import document
    workspace, root, source, value = configured
    args = Namespace(accounting_action='action-plan', input=source, accounting_root=root)
    assert cli.main(args, workspace) == 0
    planned = json.loads(capfd.readouterr().out)
    policy = document(workspace)
    policy['authorizations'] = {value['operation']: planned['authorization']}
    state = store.initialize(root, workspace, policy, hashlib.sha256(store.files.encode(policy)).hexdigest())
    result = store.append(root, workspace, dict(type='reserve', operation=value['operation'],
        run=planned['authorization']['run'], compact=None), state['head'], binding=planned['binding'])
    assert result['summary']['charged'] == planned['envelope']

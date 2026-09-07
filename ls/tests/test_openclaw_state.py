"""Framework state allocation must never adopt the OpenClaw database directory."""
from pathlib import Path

import pytest

from ls.tests.test_client_state_cli import allocation_args, invoke, repository, deterministic_safe_creation_umask


@pytest.mark.parametrize('scope', ['repo', 'global'])
def test_openclaw_state_leaves_native_and_historical_content_untouched(tmp_path, capsys, scope):
    repo = repository(tmp_path / 'repo');home = tmp_path / 'home';home.mkdir()
    base = repo if scope == 'repo' else home
    native = base / '.openclaw/state';native.mkdir(parents=True)
    preserved = {'openclaw.sqlite': b'native database fixture', 'old-framework.md': b'historical artifact'}
    for name, content in preserved.items():(native / name).write_bytes(content)
    native.chmod(0o755)
    relative = '.localsetup/client-state/openclaw/state' if scope == 'repo' else '.local/share/localsetup/client-state/openclaw/state'
    new = base / relative
    options = ['--client', 'openclaw/openclaw-cli', '--scope', scope, '--directory', str(repo)]
    code, plan = invoke(capsys, '--home', str(home), 'state', 'path', *options)
    assert code == 0, plan
    assert not new.exists()
    assert plan['state_path'] == (relative if scope == 'repo' else '~/' + relative)
    code, allocated = invoke(capsys, '--home', str(home), 'state', 'allocate', *options, *allocation_args())
    assert code == 0 and allocated['ok'], allocated
    assert (new / allocated['artifact']).is_file()
    code, verified = invoke(capsys, '--home', str(home), 'state', 'verify', *options,
                            '--artifact', allocated['artifact'])
    assert code == 0 and verified['ok'], verified
    assert {p.name: p.read_bytes() for p in native.iterdir()} == preserved
    assert native.stat().st_mode & 0o777 == 0o755


def test_old_openclaw_binding_is_rejected_after_registry_correction(tmp_path):
    from ls.tests.test_client_registry import _copy_config
    from ls.core.client_state import ClientStateError, resolve_state_location, refresh_state_location
    source = _copy_config(tmp_path)
    repo = repository(tmp_path / 'target');home = tmp_path / 'home';home.mkdir()
    catalog = source / 'ls/config/clients.yaml';current = catalog.read_text()
    catalog.write_text(current.replace('.localsetup/client-state/openclaw/state', '.openclaw/state'))
    old = resolve_state_location(source, 'openclaw/openclaw-cli', cwd=repo, home=home, scope='repo')
    catalog.write_text(current)
    with pytest.raises(ClientStateError, match='binding is stale'):
        refresh_state_location(old)
    assert not (repo / '.openclaw').exists()
    assert not (repo / '.localsetup').exists()

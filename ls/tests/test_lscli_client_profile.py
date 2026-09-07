"""Catalog registration must preserve LSCli's explicit-input authority boundary."""
import time
from pathlib import Path

import pytest
import yaml

from ls.core.client_registry import ClientRegistryError, load_client_registry, platform_rows
from ls.core.agent.diagnostics import locations
from ls.core.agent.file_grants import FileGrant
from ls.tests.test_client_registry import _copy_config

ROOT = Path(__file__).resolve().parents[2]


def test_lscli_profile_has_no_adapter_or_duplicate_state_writer(tmp_path):
    registry = load_client_registry(ROOT)
    row = registry.variant('lscli', 'lscli').data
    assert row['executables'] == ('lscli',)
    assert row['skills']['repo']['status'] == 'settings-only'
    assert row['skills']['repo']['paths'] == ()
    assert 'compatibility' not in row
    assert 'lscli' not in {entry['id'] for entry in platform_rows(registry)}
    assert row['skills']['global']['status'] == 'unsupported'
    assert all(row['state'][scope]['status'] == 'unsupported' for scope in ('repo', 'global'))
    home = tmp_path / 'home'
    assert row['config']['global']['paths'] == ('~/' + str(Path(locations(home)['profiles']).relative_to(home)),)
    assert not home.exists()
    grant = FileGrant('task', 'session', tmp_path, ('.',), (), ('.',), time.monotonic() + 5)
    grant.check('task', 'session', 'read', 'skills/example/SKILL.md', provider=True)
    with pytest.raises(PermissionError, match='protected'):
        grant.check('task', 'session', 'read', '.agents/skills/example/SKILL.md', provider=True)


@pytest.mark.parametrize('reference', ['.agents/state/ledger.md', 'ls/../private.py', '/tmp/private.py',
                                        'https://example.invalid/source.py', 'ls/core/.hidden.py'])
def test_owned_source_evidence_rejects_private_or_nonrepository_paths(tmp_path, reference):
    root = _copy_config(tmp_path)
    path = root / 'ls/config/clients.yaml'
    data = yaml.safe_load(path.read_text())
    row = next(f for f in data['families'] if f['id'] == 'lscli')['variants'][0]
    row['research']['sources'] = [{'kind': 'repository_source', 'reference': reference}]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(ClientRegistryError):
        load_client_registry(root)

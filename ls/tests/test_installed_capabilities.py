import json
from pathlib import Path
import sys

import pytest

from ls.core.agent import installed_capabilities as checks


@pytest.fixture
def release(tmp_path):
    site = tmp_path / 'venv/lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'
    config = site / 'ls/config'
    config.mkdir(parents=True)
    (config / 'sdk-runtime.lock').write_text('fixture-dependency==1.2.3\nignored==9 ; python_version < "2"\n')
    (config / 'sdk-build.lock').write_text('fixture-dependency==1.2.3\n')
    metadata = site / 'fixture_dependency-1.2.3.dist-info/METADATA'
    metadata.parent.mkdir()
    metadata.write_text('Name: fixture-dependency\nVersion: 1.2.3\n')
    return tmp_path, metadata


def test_dependency_metadata_markers_missing_and_mismatch(release):
    root, metadata = release
    assert checks.dependencies(root) == {'status': 'verified', 'expected_count': 1, 'missing': [], 'mismatched': []}
    metadata.write_text('Name: fixture-dependency\nVersion: 1.2.2\n')
    assert checks.dependencies(root)['mismatched'] == ['fixture-dependency']
    metadata.unlink()
    assert checks.dependencies(root)['missing'] == ['fixture-dependency']


@pytest.mark.parametrize('damage', ['duplicate', 'oversized', 'symlink'])
def test_invalid_metadata_is_not_readiness(release, damage):
    root, metadata = release
    if damage == 'duplicate':
        metadata.write_text('Name: fixture-dependency\nName: other\nVersion: 1.2.3\n')
    elif damage == 'oversized':
        metadata.write_bytes(b'x' * (checks.LIMIT + 1))
    else:
        metadata.unlink()
        metadata.symlink_to('/dev/zero')
    assert checks.dependencies(root) == {'status': 'unavailable'}


def test_native_presence_never_probes_execution(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, '_platform', lambda: None)
    assert checks.native(tmp_path) == {'status': 'missing', 'execution_tested': False}
    binary = tmp_path / 'venv/lscli-native/bwrap'
    binary.parent.mkdir(parents=True)
    binary.write_text('not executed')
    binary.chmod(0o700)
    assert checks.native(tmp_path) == {'status': 'present_unprobed', 'execution_tested': False}
    def unsupported():
        raise ValueError('unsupported')
    monkeypatch.setattr(checks, '_platform', unsupported)
    assert checks.native(tmp_path)['status'] == 'unsupported_platform'


@pytest.mark.parametrize('name,version', [('invalid!', '1.0'), ('extra', 'garbage')])
def test_malformed_extra_distribution_is_unavailable(release, name, version):
    root, metadata = release
    extra = metadata.parent.parent / 'extra-1.dist-info/METADATA'
    extra.parent.mkdir()
    extra.write_text(f'Name: {name}\nVersion: {version}\n')
    assert checks.dependencies(root) == {'status': 'unavailable'}

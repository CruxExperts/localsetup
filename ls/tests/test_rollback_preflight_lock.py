import json
from pathlib import Path

import pytest

from ls.core.apply import apply_plan
from ls.core.locking import package_root_lock, PackageRootLockTimeout
from ls.core.paths import global_layout
from ls.core.plan import build_install_plan
from ls.core.rollback import rollback
from ls.tests.test_install_flow import make_temp_repo


def test_rollback_waits_for_shared_lock_and_prevalidates_all_paths(tmp_path, monkeypatch):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    apply_plan(root, build_install_plan(root, home, skills=['ls-context'], platform_ids=['cursor']), home)
    receipt = root / '.localsetup/lock.json';original = receipt.read_bytes()
    lock = json.loads(original);package = Path(lock['installed_skills'][0])
    registry = Path(lock['registry_path']);before = registry.read_bytes()
    monkeypatch.setenv('LOCALSETUP_PACKAGE_ROOT_LOCK_TIMEOUT', '0')
    with package_root_lock(global_layout(home).localsetup_home):
        with pytest.raises(PackageRootLockTimeout):rollback(root, home)
    assert receipt.read_bytes() == original and registry.read_bytes() == before and package.exists()
    for field, invalid in [('installed_skills', str(tmp_path / 'outside-package')),
                           ('installed_skills', str(package.parent)),
                           ('adapter_state', str(tmp_path / 'outside-adapter'))]:
        malformed = json.loads(original);malformed[field].append(invalid)
        receipt.write_text(json.dumps(malformed))
        with pytest.raises(RuntimeError, match='refusing to rollback'):
            rollback(root, home)
        assert package.exists() and registry.read_bytes() == before
    receipt.write_bytes(original)

import json
from pathlib import Path

import pytest

from ls.core.apply import apply_plan
from ls.core.plan import build_install_plan
from ls.core.rollback import rollback
from ls.core.personal_inventory import personal_inventory
from ls.tests.test_install_flow import make_temp_repo


@pytest.mark.parametrize('mode', ['symlink', 'portable'])
def test_shared_rollback_restores_failed_transaction_and_retains_personal(tmp_path, mode, monkeypatch):
    import ls.core.shared_rollback as transaction
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    repository = build_install_plan(root, home, skills=['ls-git-workflows'], platform_ids=['cursor'],
                                    target_root=home, attach_mode=mode)
    apply_plan(root, repository, home)
    personal = build_install_plan(root, home, skills=['ls-context'], platform_ids=['openclaw'],
                                  skill_scope='personal', attach_mode=mode)
    apply_plan(root, personal, home)
    receipt = home / '.localsetup/lock.json'
    lock = json.loads(receipt.read_text());registry = Path(lock['registry_path'])
    before = (receipt.read_bytes(), registry.read_bytes())
    owners = json.loads(registry.read_text())['personal_owners']
    shared = home / '.agents/skills';(shared / 'custom.txt').write_text('preserve')
    # A nonshared adapter participates in the same transaction. Marker-listed
    # dot-prefixed packages must receive the same recovery as visible packages.
    import shutil
    from ls.core.adapter_markers import ADAPTER_MARKER_JSON
    private_adapter = home / '.cursor/skills'
    hidden = private_adapter / '.hidden-package'
    global_root = Path(lock['global_root']) if 'global_root' in lock else Path(lock['installed_skills'][0]).parent
    shutil.copytree(global_root / 'ls-git-workflows', global_root / '.hidden-package')
    if mode == 'symlink':
        hidden.symlink_to(global_root / '.hidden-package', target_is_directory=True)
    else:
        shutil.copytree(global_root / 'ls-git-workflows', hidden)
    marker_path = private_adapter / ADAPTER_MARKER_JSON
    marker = json.loads(marker_path.read_text())
    marker['packages'].append('.hidden-package')
    marker_path.write_text(json.dumps(marker))

    remove = transaction.remove_target
    def fail(*args, **kwargs):
        assert not hidden.exists() and not hidden.is_symlink()
        remove(*args, **kwargs)
        (shared / 'arrived.txt').write_text('preserve new neighbor')
        raise RuntimeError('injected after registry removal')
    monkeypatch.setattr(transaction, 'remove_target', fail)
    with pytest.raises(RuntimeError, match='injected after registry removal'):
        rollback(root, home, target_root=home)
    assert before == (receipt.read_bytes(), registry.read_bytes())
    assert (shared / 'ls-git-workflows/SKILL.md').exists()
    assert (shared / 'arrived.txt').read_text() == 'preserve new neighbor'
    assert (hidden / 'SKILL.md').exists()
    monkeypatch.setattr(transaction, 'remove_target', remove)
    result = rollback(root, home, target_root=home)
    assert json.loads(Path(result['journal']).read_text())['status'] == 'committed'
    assert not receipt.exists()
    assert not (shared / 'ls-git-workflows').exists()
    assert (shared / 'ls-context/SKILL.md').exists()
    assert (shared / 'custom.txt').read_text() == 'preserve'
    after = json.loads(registry.read_text())
    assert str(home.resolve()) not in after['targets']
    assert after['personal_owners'] == owners
    report = personal_inventory(root, home)
    assert report['ok'], report['issues']

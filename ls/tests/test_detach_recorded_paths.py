import json
from pathlib import Path

import pytest

from ls.core.apply import apply_plan
from ls.core.detach import detach_platforms
from ls.core.plan import build_install_plan
from ls.tests.test_install_flow import make_temp_repo


def test_detach_uses_recorded_path_after_catalog_change(tmp_path):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    apply_plan(root, build_install_plan(root, home, skills=['ls-context'], platform_ids=['cursor']), home)
    receipt = root / '.localsetup/lock.json';lock = json.loads(receipt.read_text())
    old = root / '.cursor/skills';(old / 'custom.txt').write_text('keep')
    catalog = root / 'ls/config/platforms.yaml'
    catalog.write_text(catalog.read_text().replace('.cursor/skills', '.new-cursor/skills'))
    fresh = root / '.new-cursor/skills';fresh.mkdir(parents=True)
    library = Path(lock['installed_skills'][0]).parent
    (fresh / 'ls-context').symlink_to(library / 'ls-context', target_is_directory=True)
    detach_platforms(root, home, root, ['cursor'])
    assert not (old / 'ls-context').exists()
    assert (old / 'custom.txt').read_text() == 'keep'
    assert (fresh / 'ls-context').is_symlink()
    assert not json.loads(receipt.read_text())['adapter_targets']


@pytest.mark.parametrize('typed', [True, False])
def test_detach_preserves_explicit_empty_recorded_ownership(tmp_path, typed):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    apply_plan(root, build_install_plan(root, home, skills=['ls-context'], platform_ids=['cursor']), home)
    receipt = root / '.localsetup/lock.json';lock = json.loads(receipt.read_text())
    for row in lock['adapter_targets']:
        if typed:row['owners'] = []
        else:
            row.pop('owners');row['platforms'] = []
    receipt.write_text(json.dumps(lock))
    registry = Path(lock['registry_path']);before = receipt.read_bytes(), registry.read_bytes()
    assert not detach_platforms(root, home, root, ['cursor'])['removed']
    assert before == (receipt.read_bytes(), registry.read_bytes())
    assert (root / '.cursor/skills/ls-context').exists()


def test_detach_rejects_later_outside_record_before_removal(tmp_path):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    apply_plan(root, build_install_plan(root, home, skills=['ls-context'], platform_ids=['cursor']), home)
    receipt = root / '.localsetup/lock.json';lock = json.loads(receipt.read_text())
    lock['adapter_targets'].append(dict(lock['adapter_targets'][0], path=str(tmp_path / 'outside')))
    receipt.write_text(json.dumps(lock))
    with pytest.raises(ValueError, match='escapes target'):detach_platforms(root, home, root, ['cursor'])
    assert (root / '.cursor/skills/ls-context').exists()

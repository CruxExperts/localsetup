import json
from pathlib import Path

import pytest

from ls.core.apply import apply_plan
from ls.core.personal_update import build_recorded_personal_plan
from ls.tests.test_install_flow import make_temp_repo
from ls.core.plan import build_install_plan


@pytest.mark.parametrize('mode', ['symlink', 'portable'])
def test_recorded_personal_update_refreshes_without_reselection(tmp_path, mode):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home'
    for clients, names in [(['cursor'], ['ls-context']), (['openclaw'], ['ls-git-workflows'])]:
        plan = build_install_plan(root, home, skills=names, platform_ids=clients,
                                  skill_scope='personal', attach_mode=mode)
        apply_plan(root, plan, home)
    receipt = root / '.localsetup/lock.json'
    lock = json.loads(receipt.read_text())
    # Both recorded owners are the selected update target, with different selections.
    lock['platforms'] = ['cursor', 'openclaw']
    receipt.write_text(json.dumps(lock))
    registry_path = Path(lock['registry_path'])
    before = json.loads(registry_path.read_text())['personal_owners']
    (home / '.agents/skills/custom.txt').write_text('preserve')
    source = root / 'ls/skills/ls-context/SKILL.md'
    source.write_text(source.read_text() + '\nFixture update text.\n')
    plan = build_recorded_personal_plan(root, home, root)
    assert json.loads(registry_path.read_text())['personal_owners'] == before
    actions = [a for a in plan.actions if a.kind == 'attach_personal_path']
    assert len({str(a.path) for a in actions}) == len(actions)
    assert all(a.details['mode'] == mode for a in actions)
    apply_plan(root, plan, home)
    assert json.loads(registry_path.read_text())['personal_owners'] == before
    assert 'Fixture update text.' in (home / '.agents/skills/ls-context/SKILL.md').read_text()
    assert (home / '.agents/skills/custom.txt').read_text() == 'preserve'
    stale = build_recorded_personal_plan(root, home, root)
    registry_path.write_text(registry_path.read_text() + '\n')
    original = receipt.read_bytes()
    with pytest.raises(RuntimeError, match='stale_recorded_plan'):
        apply_plan(root, stale, home)
    assert receipt.read_bytes() == original

import json
from pathlib import Path

from ls.core import cli
from ls.core.apply import apply_plan
from ls.core.plan import build_install_plan
from ls.tests.test_install_flow import make_temp_repo


def test_cli_automatic_personal_plan_update_and_repair_first(tmp_path, capsys):
    root = make_temp_repo(tmp_path);home = tmp_path / 'home';target = tmp_path / 'target'
    target.mkdir()
    apply_plan(root, build_install_plan(root, home, skills=['ls-context'], platform_ids=['cursor'],
                                        target_root=target, skill_scope='personal'), home)
    receipt = target / '.localsetup/lock.json'
    registry = Path(json.loads(receipt.read_text())['registry_path'])
    owners = json.loads(registry.read_text())['personal_owners']
    before = (receipt.read_bytes(), registry.read_bytes())
    def invoke(command):
        result = cli._main(['--source-root', str(root), '--home', str(home), command,
                            '--target-directory', str(target)])
        payload = json.loads(capsys.readouterr().out)
        assert result == 0, payload
        return payload
    planned = invoke('plan')
    assert planned['auto_mode'] == 'recorded_personal'
    assert planned['rollback']['skill_scope'] == 'personal'
    assert before == (receipt.read_bytes(), registry.read_bytes())
    source = root / 'ls/skills/ls-context/SKILL.md'
    source.write_text(source.read_text() + '\nCLI fixture update.\n')
    updated = invoke('update')
    assert updated['ok'] and updated['auto_mode'] == 'recorded_personal'
    assert json.loads(registry.read_text())['personal_owners'] == owners
    assert 'CLI fixture update.' in (home / '.agents/skills/ls-context/SKILL.md').read_text()
    (home / '.agents/skills/ls-context').unlink()
    repair = invoke('plan')
    assert repair['auto_mode'] == 'repair_required'
    assert any(a['kind'] == 'attach_personal_path' for a in repair['actions'])
    assert not (home / '.agents/skills/ls-context').exists()

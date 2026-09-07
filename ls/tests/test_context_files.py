import json
from pathlib import Path
import time

import pytest

from ls.core.agent.context_files import selection, include
from ls.core.agent.file_broker import FileBroker
from ls.core.agent.file_grants import FileGrant
from ls.core.agent.session_owner import lease


def test_explicit_context_and_skill_snapshot_preserve_bytes(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    (workspace/'AGENTS.md').write_text('Project instructions\n')
    (workspace/'skill').mkdir();(workspace/'skill/SKILL.md').write_text('---\nname: fixture\ndescription: test\n---\nUse the selected fixture.')
    sessions=tmp_path/'sessions';sessions.mkdir(mode=0o700)
    locks=tmp_path/'locks';locks.mkdir(mode=0o700)
    grant=FileGrant('task','session',workspace,('.',),(),('.',),time.monotonic()+5)
    with lease(sessions,task='task',session='session',workspace=workspace,expires=grant.expires) as owner:
        result=include('Task',selection(['AGENTS.md'],['skill/SKILL.md']),owner,FileBroker(grant,locks))
        resources=json.loads(result.split('external):\n',1)[1])
        assert [r['kind'] for r in resources]==['context','skill']
        assert resources[0]['content']=='Project instructions\n' and len(resources[0]['sha256'])==64
        denied=FileGrant('task','session',workspace,('.',),(),(),grant.expires)
        with pytest.raises(PermissionError,match='disclosure'):include('Task',selection(['AGENTS.md'],[]),owner,FileBroker(denied,locks))
        (workspace/'linked').symlink_to(workspace/'AGENTS.md')
        with pytest.raises(OSError):include('Task',selection(['linked'],[]),owner,FileBroker(grant,locks))
        (workspace/'large').write_text('x'*(16*1024+1))
        with pytest.raises(ValueError,match='byte limit'):include('Task',selection(['large'],[]),owner,FileBroker(grant,locks))
        assert owner.inspect()=={}
    assert (workspace/'AGENTS.md').read_text()=='Project instructions\n'


@pytest.mark.parametrize('context,skills', [(['../escape'],[]),(['x']*17,[]),(['x','x'],[]),([],['skill/README.md']),(['x'],['x'])])
def test_selection_rejects_unsafe_or_ambiguous_inputs(context,skills):
    with pytest.raises((ValueError,PermissionError)):selection(context,skills)

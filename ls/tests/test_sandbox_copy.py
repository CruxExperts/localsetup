from dataclasses import replace
import os
from pathlib import Path
import stat

import pytest
from ls.core.agent.sandbox_copy import copy_inputs
from ls.tests.test_agent_sandbox import invocation


def test_copy_is_disposable_and_preserves_owner_execute(tmp_path):
    source,target=tmp_path/'source',tmp_path/'target';source.mkdir();target.mkdir()
    (source/'dir').mkdir();(source/'dir/a').write_text('original');(source/'dir/a').chmod(0o700)
    copy_inputs(source,target)
    assert stat.S_IMODE((target/'dir/a').stat().st_mode)==0o700
    (target/'dir/a').write_text('changed')
    assert (source/'dir/a').read_text()=='original'


@pytest.mark.parametrize('kind',['symlink','hardlink','fifo'])
def test_copy_refuses_unsafe_entries(tmp_path,kind):
    source,target=tmp_path/'source',tmp_path/'target';source.mkdir();target.mkdir()
    if kind=='symlink':(source/'unsafe').symlink_to('/usr')
    elif kind=='fifo':os.mkfifo(source/'unsafe')
    else:
        (source/'one').write_text('x');os.link(source/'one',source/'unsafe')
    with pytest.raises(ValueError,match='regular'):copy_inputs(source,target)


def test_copy_scan_error_is_not_ignored(tmp_path,monkeypatch):
    def walk(*args,**kwargs):kwargs['onerror'](PermissionError('denied'))
    monkeypatch.setattr(os,'walk',walk)
    with pytest.raises(PermissionError):copy_inputs(tmp_path,tmp_path)


@pytest.mark.parametrize('field,value',[('work_bytes',True),('temporary_bytes',0),('work_bytes',2**40)])
def test_writable_bounds_require_finite_integer_grants(invocation,field,value):
    with pytest.raises(ValueError,match='storage'):replace(invocation[1],**{field:value})

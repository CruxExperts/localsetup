import threading
import time

import pytest

from ls.core.agent.steering import Steering
from ls.core.agent.coding_protocol import CodingHandler
from test_coding_protocol import handler


def message(**changes):
    return dict(schema_version=1,id=1,method='steer',task='task',session='session',profile='profile',text='new direction',disclose=True)|changes


def test_fresh_identity_disclosure_and_consumption():
    cancelled=threading.Event();queue=Steering(cancelled,time.monotonic()+10)
    with pytest.raises(PermissionError):queue.accept(message())
    queue.bind('task','session','profile')
    for changed in [{'task':'foreign'},{'session':'foreign'},{'profile':'foreign'},{'disclose':False}]:
        with pytest.raises(PermissionError):queue.accept(message(**changed))
    queue.accept(message());assert queue.take()==['new direction'] and queue.take()==[]
    cancelled.set()
    with pytest.raises(PermissionError):queue.accept(message())
    with pytest.raises(PermissionError):queue.take()


def test_cumulative_bounds_and_rpc_authority_checks():
    queue=Steering(threading.Event(),time.monotonic()+10);queue.bind('task','session','profile')
    for _ in range(16):queue.accept(message(text='x'*8192));queue.take()
    with pytest.raises(ValueError):queue.accept(message(text='x'))
    h,events,checks=handler()
    h.steering=lambda:['new direction']
    with pytest.raises(ValueError):h('run.steering',{})
    h('run.start',{});assert h('run.steering',{})=={'messages':['new direction']}
    assert checks[-2:]==['authority','authority'] and not events

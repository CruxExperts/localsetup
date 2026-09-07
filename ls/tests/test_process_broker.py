from contextlib import contextmanager
import threading
import time

import pytest

from ls.core.agent import process_broker as broker
from ls.core.agent.sandbox import Invocation, ProcessGrant


@pytest.fixture
def runner(tmp_path, monkeypatch):
    held = []
    @contextmanager
    def invocation(root, grant, **kwargs):
        held.append(True)
        try:
            yield Invocation(grant.command, tmp_path, {})
        finally:
            held.pop()
    monkeypatch.setattr(broker, 'invocation', invocation)
    def run(code, *, disclose=False, provider=False, timeout=2, cancel=None, revoke=False):
        # Fixture launches Python directly to isolate broker transport tests.
        grant = ProcessGrant('task', 'session', tmp_path,
                             ('/usr/bin/python3', '-I', '-B', '-c', code),
                             time.monotonic()+timeout, disclose_output=disclose)
        timer = threading.Timer(.05, grant.revoked.set) if revoke else None
        if timer:
            timer.start()
        try:
            result = broker.run(tmp_path, grant, task='task', session='session', provider=provider, cancel=cancel)
            assert not held
            return result
        finally:
            if timer:
                timer.cancel();timer.join()
    return run


def test_capture_preserves_nonzero_failure_and_diagnostics(runner):
    result = runner("import sys;print('out');sys.stderr.write('err');sys.exit(7)")
    assert result.status == 'failed' and result.returncode == 7
    assert result.data == {'stdout': 'out\n', 'stderr': 'err'}
    result = runner("import sys;sys.stdout.buffer.write(b'\\xff')", disclose=True, provider=True)
    assert result.status == 'completed' and result.data == {'stdout': '\ufffd', 'stderr': ''}


def test_provider_disclosure_refuses_before_dispatch(runner, monkeypatch):
    monkeypatch.setattr(broker, 'supervise', lambda *args, **kwargs: pytest.fail('must not dispatch'))
    with pytest.raises(PermissionError, match='disclosure'):
        runner('raise AssertionError()', provider=True)


@pytest.mark.parametrize('stream,amount', [('stdout', 1024*1024+1), ('stderr', 64*1024+1)])
def test_overflow_discards_capture(runner, stream, amount):
    result = runner(f"import sys,time;sys.{stream}.buffer.write(b'x'*{amount});sys.{stream}.flush();time.sleep(30)")
    assert result.status == 'output_limit' and result.data is None


def test_deadline_and_revocation_discard_partial_output(runner):
    code = "import time;print('partial',flush=True);time.sleep(30)"
    result = runner(code, timeout=.05)
    assert result.status == 'timed_out' and result.data is None
    result = runner(code, revoke=True)
    assert result.status == 'cancelled' and result.data is None


def test_precancel_avoids_launch(runner, monkeypatch):
    monkeypatch.setattr(broker, 'invocation', lambda *args, **kwargs: pytest.fail('must not launch'))
    cancel = threading.Event();cancel.set()
    result = runner('raise AssertionError()', cancel=cancel)
    assert result.status == 'cancelled' and result.returncode is None


def test_recheck_after_capture_refuses_revoked_output(tmp_path, monkeypatch):
    grant = ProcessGrant('task', 'session', tmp_path, ('/usr/bin/true',), time.monotonic()+1, disclose_output=True)
    @contextmanager
    def invocation(*args, **kwargs):
        yield Invocation(grant.command, tmp_path, {})
    monkeypatch.setattr(broker, 'invocation', invocation)
    def supervise(*args, **kwargs):
        grant.revoked.set()
        return broker.Outcome('completed', 0, {'stdout': 'must not escape', 'stderr': ''})
    monkeypatch.setattr(broker, 'supervise', supervise)
    result = broker.run(tmp_path, grant, task='task', session='session', provider=True)
    assert result.status == 'cancelled' and result.data is None

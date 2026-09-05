"""Bounded POSIX worker lifetime; terminal outcomes belong to the supervisor."""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

from .runtime_install import selected
from .worker_protocol import MAX_REQUEST, MAX_OUTPUT, MAX_DIAGNOSTICS, result


@dataclass(frozen=True)
class Outcome:
    status: str
    returncode: int | None
    data: dict | None = None


def _kill(process) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def supervise(command: list[str], request: bytes, *, cwd: Path, environment: dict[str, str], timeout: float, cancel=None) -> Outcome:
    if os.name != 'posix':
        raise RuntimeError('Worker supervision requires qualified POSIX process groups')
    if not math.isfinite(timeout) or timeout <= 0 or len(request) > MAX_REQUEST:
        raise ValueError('Invalid worker deadline or request size')
    if cancel is not None and cancel.is_set():
        return Outcome('cancelled', None)
    deadline = time.monotonic() + timeout
    process = subprocess.Popen(command, cwd=cwd, env=environment, stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True, umask=0o077)
    output, diagnostics = bytearray(), bytearray()
    status, offset = None, 0
    try:
        with selectors.DefaultSelector() as selector:
            for stream, kind, events in ((process.stdin, 'input', selectors.EVENT_WRITE),
                    (process.stdout, 'output', selectors.EVENT_READ), (process.stderr, 'diagnostics', selectors.EVENT_READ)):
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, events, kind)
            while selector.get_map():
                if cancel is not None and cancel.is_set():
                    status = 'cancelled'
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    status = 'timed_out'
                    break
                if process.poll() is not None:
                    # Descendants cannot retain pipes after the owning worker exits.
                    _kill(process)
                for key, _ in selector.select(min(remaining, 0.05)):
                    stream = key.fileobj
                    if key.data == 'input':
                        try:
                            offset += os.write(stream.fileno(), request[offset:])
                        except BrokenPipeError:
                            offset = len(request)
                        if offset == len(request):
                            selector.unregister(stream)
                            stream.close()
                        continue
                    try:
                        chunk = os.read(stream.fileno(), 16384)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(stream)
                        stream.close()
                        continue
                    target, limit = (output, MAX_OUTPUT) if key.data == 'output' else (diagnostics, MAX_DIAGNOSTICS)
                    if len(target) + len(chunk) > limit:
                        status = 'output_limit'
                        break
                    target.extend(chunk)
                if status is not None:
                    break
            if status is None:
                while process.poll() is None:
                    if cancel is not None and cancel.is_set():
                        status = 'cancelled'
                        break
                    if time.monotonic() >= deadline:
                        status = 'timed_out'
                        break
                    try:
                        process.wait(timeout=min(0.05, max(0.001, deadline-time.monotonic())))
                    except subprocess.TimeoutExpired:
                        pass
    except KeyboardInterrupt:
        status = 'cancelled'
    finally:
        _kill(process)
        process.wait()
        for stream in (process.stdin, process.stdout, process.stderr):
            if not stream.closed:
                stream.close()
    if status is not None:
        return Outcome(status, process.returncode)
    if process.returncode != 0:
        return Outcome('failed', process.returncode)
    try:
        data = result(bytes(output))
    except (ValueError, TypeError, RecursionError):
        return Outcome('protocol_error', process.returncode)
    return Outcome('completed', process.returncode, data)


def probe_runtime(root: Path, *, timeout: float = 30, cancel=None) -> Outcome:
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Worker timeout must be finite and positive')
    deadline = time.monotonic() + timeout
    if cancel is not None and cancel.is_set():
        return Outcome('cancelled', None)
    with selected(root, timeout=timeout) as release:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return Outcome('timed_out', None)
        return supervise([str(release/'venv/bin/python'), '-I', '-B', '-m', 'ls.core.agent.sdk_worker', '--serve'],
            json.dumps({'schema_version': 1, 'operation': 'probe'}).encode(), cwd=release,
            environment={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, timeout=remaining, cancel=cancel)

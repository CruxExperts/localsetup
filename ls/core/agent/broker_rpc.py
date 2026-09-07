"""Bounded inherited-socket RPC; a lost acknowledgement never triggers replay."""
from __future__ import annotations

import asyncio
import json
import math
import selectors
import socket
import struct
import threading
import time

from .operation_journal import IDENTIFIER

MAX_FRAME = 16 * 1024 * 1024
MAX_BYTES = 64 * 1024 * 1024
MAX_CALLS = 10000


def _encode(value):
    raw = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    if len(raw) > MAX_FRAME:
        raise ValueError('RPC frame exceeds byte limit')
    return raw


def _decode(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate RPC key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Non-finite RPC number')
    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError('Non-finite RPC number')
        return result
    return json.loads(raw, object_pairs_hook=unique, parse_constant=constant, parse_float=number)


class Channel:
    def __init__(self, connection, *, task, session, methods, expires, cancelled=None):
        if connection.family != socket.AF_UNIX or connection.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM:
            raise ValueError('RPC requires an inherited connected Unix stream socket')
        connection.getpeername()
        if any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in (task, session)):
            raise ValueError('RPC requires explicit bounded identities')
        if not isinstance(methods, frozenset) or not methods or any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in methods):
            raise ValueError('RPC requires an explicit immutable method allowlist')
        if not math.isfinite(expires) or expires <= time.monotonic():
            raise TimeoutError('RPC deadline expired')
        self.connection, self.task, self.session, self.methods = connection, task, session, methods
        self.expires, self.cancelled = expires, cancelled or threading.Event()
        self.sequence, self.used, self.closed = 0, 0, False
        self._busy = threading.Lock()
        connection.setblocking(False)

    def close(self):
        self.closed = True
        try:
            self.connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.connection.close()

    def _check(self):
        if self.closed or self.cancelled.is_set():
            raise ConnectionError('RPC channel is closed or cancelled; reconcile pending effects')
        if time.monotonic() >= self.expires:
            raise TimeoutError('RPC deadline expired; reconcile pending effects')

    def _transfer(self, *, data=None, size=None):
        self._check()
        sending = data is not None
        result = bytearray()
        remaining = memoryview(data) if sending else None
        with selectors.DefaultSelector() as selector:
            selector.register(self.connection, selectors.EVENT_WRITE if sending else selectors.EVENT_READ)
            while (len(remaining) if sending else size-len(result)):
                self._check()
                if not selector.select(min(.05, max(0, self.expires-time.monotonic()))):
                    continue
                try:
                    if sending:
                        count = self.connection.send(remaining)
                        if count == 0:
                            raise ConnectionError('RPC connection ended during send')
                        remaining = remaining[count:]
                    else:
                        chunk = self.connection.recv(min(65536, size-len(result)))
                        if not chunk:
                            raise ConnectionError('RPC connection ended before acknowledgement')
                        result.extend(chunk)
                except BlockingIOError:
                    continue
        self._check()
        return bytes(result)

    def _send(self, value):
        raw = _encode(value)
        if self.used+4+len(raw) > MAX_BYTES:
            raise ValueError('RPC aggregate byte limit exceeded')
        self.used += 4+len(raw)
        self._transfer(data=struct.pack('!I',len(raw))+raw)

    def _receive(self):
        size, = struct.unpack('!I',self._transfer(size=4))
        if size > MAX_FRAME or self.used+4+size > MAX_BYTES:
            raise ValueError('RPC incoming frame or aggregate limit exceeded')
        self.used += 4+size
        return _decode(self._transfer(size=size))

    def _envelope(self, kind, data, method=None):
        if not isinstance(data, dict):
            raise ValueError('RPC payload must be an object')
        value = {'schema_version':1,'task':self.task,'session':self.session,
                 'sequence':self.sequence,'type':kind,'data':data}
        if method is not None:
            value['method'] = method
        return value

    def _validate(self, value, kind):
        keys = {'schema_version','task','session','sequence','type','data'} | ({'method'} if kind == 'request' else set())
        if (not isinstance(value, dict) or set(value) != keys or type(value['schema_version']) is not int
                or value['schema_version'] != 1 or type(value['sequence']) is not int or value['sequence'] != self.sequence
                or value['task'] != self.task or value['session'] != self.session or value['type'] != kind
                or not isinstance(value['data'], dict)):
            raise ValueError('RPC envelope identity, schema or sequence mismatch')
        if kind == 'request' and (not isinstance(value['method'], str) or value['method'] not in self.methods):
            raise PermissionError('RPC method is outside the allowlist')

    def _enter(self):
        try:
            self._check()
        except BaseException:
            self.close()
            raise
        if not self._busy.acquire(blocking=False):
            raise RuntimeError('RPC call is already outstanding')
        if self.sequence >= MAX_CALLS:
            self._busy.release()
            self.close()
            raise ValueError('RPC call count limit exceeded')

    def request(self, method, data):
        self._enter()
        try:
            if not isinstance(method, str) or method not in self.methods:
                raise PermissionError('RPC method is outside the allowlist')
            self._send(self._envelope('request',data,method))
            result = self._receive()
            self._validate(result,'result')
            self._check()
            self.sequence += 1
            return result['data']
        except BaseException:
            self.close()
            raise
        finally:
            self._busy.release()

    async def request_async(self, method, data):
        try:
            return await asyncio.to_thread(self.request, method, data)
        except BaseException:
            self.close()
            raise

    def serve_once(self, handler, *, check):
        self._enter()
        try:
            request = self._receive()
            self._validate(request,'request')
            check()
            self._check()
            result = handler(request['method'],request['data'])
            check()
            self._check()
            self._send(self._envelope('result',result))
            self.sequence += 1
        except BaseException:
            self.close()
            raise
        finally:
            self._busy.release()

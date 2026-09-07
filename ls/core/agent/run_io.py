"""Bounded CLI descriptor I/O and safe text rendering."""
from contextlib import contextmanager
import json
import os
import select
import time


def safe(text):
    return ''.join(character if character in '\n\t' or (character.isprintable() and not 0x202a <= ord(character) <= 0x202e and not 0x2066 <= ord(character) <= 0x2069)
                   else '\\u%04x' % ord(character) for character in text)


class Streams:
    def __init__(self, expires, cancelled, *, input_fd=0, output_fd=1):
        self.expires, self.cancelled = expires, cancelled
        self.input_fd, self.output_fd = input_fd, output_fd
        self.written = 0
        self.sequence = 0

    def check(self):
        if self.cancelled.is_set():
            raise InterruptedError('Run cancelled')
        if time.monotonic() >= self.expires:
            raise TimeoutError('Run deadline expired')

    def prompt(self):
        data = bytearray()
        while True:
            self.check()
            if not select.select([self.input_fd],[],[],min(0.05,max(0,self.expires-time.monotonic())))[0]:
                continue
            raw = os.read(self.input_fd,min(4096,128*1024+1-len(data)))
            if not raw:
                break
            data.extend(raw)
            if len(data) > 128*1024:
                raise ValueError('Prompt exceeds 128 KiB')
        if not data or not data.decode().strip():
            raise ValueError('Prompt must contain UTF-8 text')
        return data.decode()

    def write(self, text):
        data = text.encode('utf-8')
        if self.written+len(data)>4*1024*1024:
            raise ValueError('CLI output exceeds 4 MiB')
        with self._nonblocking():
            while data:
                self.check()
                if not select.select([],[self.output_fd],[],min(0.05,max(0,self.expires-time.monotonic())))[1]:
                    continue
                try:
                    size = os.write(self.output_fd,data[:4096])
                except BlockingIOError:
                    continue
                if size <= 0:
                    raise BrokenPipeError('Output closed')
                self.written += size
                data = data[size:]

    @contextmanager
    def _nonblocking(self):
        original = os.get_blocking(self.output_fd)
        os.set_blocking(self.output_fd,False)
        try:
            yield
        finally:
            os.set_blocking(self.output_fd,original)

    def event(self, sequence, kind, data):
        self.sequence = sequence
        self.write(json.dumps({'schema_version':1,'sequence':sequence,'type':kind,'data':data},ensure_ascii=True,allow_nan=False)+'\n')

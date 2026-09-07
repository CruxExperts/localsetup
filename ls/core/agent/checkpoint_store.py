"""Immutable bounded conversation evidence; never restores tool authority."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import stat
import uuid

from .operation_journal import DIGEST, IDENTIFIER
from .runtime_lock import _directory, runtime_use, LOCK_NAME

MAX_MESSAGES = 8 * 1024 * 1024
MAX_RECORD = 16 * 1024 * 1024
MAX_COUNT = 1000
MAX_TOTAL = 256 * 1024 * 1024


def _encode(value):
    raw = (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)+'\n').encode()
    if len(raw) > MAX_RECORD:
        raise ValueError('Checkpoint exceeds 16 MiB record limit')
    return raw


def _validate(value):
    required = {'schema_version','task','session','profile','run_id','step','state','frontier','messages'}
    if not isinstance(value, dict) or set(value) != required or type(value['schema_version']) is not int or value['schema_version'] != 1:
        raise ValueError('Invalid checkpoint schema')
    if any(not isinstance(value[k], str) or not IDENTIFIER.fullmatch(value[k]) for k in ('task','session','run_id')):
        raise ValueError('Invalid checkpoint identity')
    if any(not isinstance(value[k], str) or not DIGEST.fullmatch(value[k]) for k in ('profile','frontier')):
        raise ValueError('Invalid checkpoint evidence digest')
    if type(value['step']) is not int or value['step'] < 0 or value['state'] not in ('complete','interrupted'):
        raise ValueError('Invalid checkpoint step or state')
    messages = value['messages']
    if not isinstance(messages, str) or len(messages.encode()) > MAX_MESSAGES or not isinstance(json.loads(messages), list):
        raise ValueError('Checkpoint requires bounded serialized SDK message array')


def _read(directory, name, validate=_validate):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o7077:
            raise ValueError('Checkpoint must be a private owned regular file')
        with os.fdopen(fd, 'rb', closefd=False) as stream:
            raw = stream.read(MAX_RECORD+1)
        if len(raw) > MAX_RECORD or hashlib.sha256(raw).hexdigest()+'.json' != name:
            raise ValueError('Checkpoint size or digest mismatch')
        value = json.loads(raw)
        validate(value)
        if _encode(value) != raw:
            raise ValueError('Checkpoint encoding is not canonical')
        return raw, value
    finally:
        os.close(fd)


class Checkpoints:
    def __init__(self, root: Path, *, validate=_validate):
        self.root = root.absolute()
        self._validate = validate

    def save(self, value, *, timeout=30):
        self._validate(value)
        raw = _encode(value)
        digest = hashlib.sha256(raw).hexdigest()
        with runtime_use(self.root, exclusive=True, timeout=timeout):
            directory = _directory(self.root)
            try:
                if os.fstat(directory).st_mode & 0o077:
                    raise ValueError('Checkpoint root must be private')
                names = os.listdir(directory)
                entries = [name for name in names if name != LOCK_NAME]
                records = [name for name in entries if not re.fullmatch(r'\.pending-[0-9a-f]{32}', name)]
                if len(entries) > MAX_COUNT:
                    raise ValueError('Checkpoint count limit exceeded')
                total = 0
                for name in set(entries)-set(records):
                    info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid() or info.st_mode & 0o7077 or info.st_size > MAX_RECORD:
                        raise ValueError('Interrupted checkpoint must be a bounded private regular file')
                    total += info.st_size
                for name in records:
                    data, _ = _read(directory, name, self._validate)
                    total += len(data)
                    if total > MAX_TOTAL:
                        raise ValueError('Checkpoint storage exceeds byte limit')
                name = digest+'.json'
                if name not in records:
                    if len(entries) >= MAX_COUNT or total+len(raw) > MAX_TOTAL:
                        raise ValueError('Checkpoint storage is full')
                    temporary = '.pending-'+uuid.uuid4().hex
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
                    with os.fdopen(fd, 'wb') as stream:
                        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
                    os.rename(temporary, name, src_dir_fd=directory, dst_dir_fd=directory)
                elif total > MAX_TOTAL:
                    raise ValueError('Checkpoint storage exceeds byte limit')
                # Also flush a rediscovered immutable record before acknowledging it.
                os.fsync(directory)
                return digest
            finally:
                os.close(directory)

    def load(self, digest, *, timeout=30):
        if not isinstance(digest, str) or not DIGEST.fullmatch(digest):
            raise ValueError('Invalid checkpoint digest')
        with runtime_use(self.root, timeout=timeout):
            directory = _directory(self.root)
            try:
                if os.fstat(directory).st_mode & 0o077:
                    raise ValueError('Checkpoint root must be private')
                return _read(directory, digest+'.json', self._validate)[1]
            finally:
                os.close(directory)

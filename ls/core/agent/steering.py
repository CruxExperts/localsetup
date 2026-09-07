"""Fresh owner text disclosure scoped to one active task, session and profile."""
import threading
import time


class Steering:
    def __init__(self, cancelled, expires):
        self.cancelled, self.expires = cancelled, expires
        self.identity = None
        self.pending = []
        self.count = self.bytes = 0
        self.lock = threading.Lock()

    def bind(self, task, session, profile):
        with self.lock:
            if self.identity is not None:
                raise ValueError('Steering identity already bound')
            self.identity = (task, session, profile)

    def check(self):
        if self.cancelled.is_set() or time.monotonic() >= self.expires:
            raise PermissionError('Steering authority ended')

    def accept(self, value):
        with self.lock:
            self.check()
            if (set(value) != {'schema_version','id','method','task','session','profile','text','disclose'}
                    or self.identity is None or (value['task'],value['session'],value['profile']) != self.identity
                    or value['disclose'] is not True):
                raise PermissionError('Steering requires matching identity and explicit text disclosure')
            text = value['text']
            if not isinstance(text,str) or not text or len(text.encode()) > 8192:
                raise ValueError('Steering text exceeds bounds')
            if self.count >= 32 or self.bytes+len(text.encode()) > 128*1024:
                raise ValueError('Steering budget exceeded')
            self.pending.append(text)
            self.count += 1
            self.bytes += len(text.encode())

    def take(self):
        with self.lock:
            self.check()
            result, self.pending = self.pending, []
            return result

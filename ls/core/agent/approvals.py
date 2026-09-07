"""One-use owner confirmation of concrete requests within existing tool grants."""
import hashlib
import json
import threading
import uuid

from .broker_rpc import _encode


class Approvals:
    def __init__(self):
        self.identity = None
        self.pending = None
        self.lock = threading.Lock()
        self.ready = threading.Event()

    def bind(self, task, session, profile):
        if self.identity is not None:
            raise ValueError('Approval identity already bound')
        self.identity = (task, session, profile)

    def decide(self, value):
        with self.lock:
            if (set(value) != {'schema_version','id','method','task','session','profile','challenge','sha256','allow'}
                    or self.identity is None or (value['task'],value['session'],value['profile']) != self.identity
                    or type(value['allow']) is not bool or self.pending is None
                    or value['challenge'] != self.pending['challenge'] or value['sha256'] != self.pending['sha256']
                    or self.ready.is_set()):
                raise PermissionError('Approval does not match a pending request')
            self.pending['allow'] = value['allow']
            self.ready.set()

    def require(self, method, data, recipes, emit, check):
        check()
        retained = json.loads(_encode(data))
        if not isinstance(retained,dict):
            raise ValueError('Approval request arguments must be an object')
        preview = {'method':method,'arguments':retained}
        if method == 'context.refresh':
            if set(retained)!={'directory'}:
                raise ValueError('Invalid context refresh approval schema')
            from .nested_context import candidates
            preview['context_paths']=candidates(retained['directory'])
        if method == 'process.run':
            recipe = recipes.get(retained.get('name'))
            if recipe is None:
                raise PermissionError('Process recipe is not granted')
            preview['recipe'] = {'command':list(recipe.command),'files':list(recipe.files),'seconds':recipe.seconds}
        raw = _encode(preview)
        if len(raw) > 128*1024:
            raise ValueError('Complete approval preview exceeds 128 KiB')
        with self.lock:
            if self.identity is None or self.pending is not None:
                raise PermissionError('Approval has no active identity or is already pending')
            self.ready.clear()
            self.pending = {'challenge':uuid.uuid4().hex,'sha256':hashlib.sha256(raw).hexdigest()}
            packet = dict(self.pending,task=self.identity[0],session=self.identity[1],profile=self.identity[2],request=preview)
        try:
            emit(json.loads(_encode(packet)))
            while not self.ready.wait(0.02):
                check()
            check()
            with self.lock:
                allowed = self.pending['allow']
            if not allowed:
                raise PermissionError('Owner denied the tool request')
            return retained
        finally:
            with self.lock:
                self.pending = None
                self.ready.clear()

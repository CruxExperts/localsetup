"""Manifest-backed SDK imports, installed only in the isolated worker process."""
from __future__ import annotations

import hashlib
import importlib.abc
import importlib.util
from pathlib import Path
import sys

from ..sdk_payload.integrity import COMPONENTS, verify


def owns(name: str) -> bool:
    return name.split('.', 1)[0] in COMPONENTS.values()


class PayloadLoader(importlib.abc.Loader):
    def __init__(self, path: Path, digest: str):
        self.path, self.digest = path, digest

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        # Compile the verified source bytes, never ambient or cached bytecode.
        if self.path.is_symlink():
            raise ImportError('SDK source cannot be a symlink')
        source = self.path.read_bytes()
        if hashlib.sha256(source).hexdigest() != self.digest:
            raise ImportError('SDK source changed after payload verification')
        exec(compile(source, str(self.path), 'exec', dont_inherit=True), module.__dict__)

    def get_resource_reader(self, fullname):
        from importlib.resources.readers import FileReader
        return FileReader(self)


class PayloadFinder(importlib.abc.MetaPathFinder):
    def __init__(self, root: Path, manifest: dict):
        self.root = root
        self.entries = manifest['files']
        self.loaded = {}

    def find_spec(self, fullname, path=None, target=None):
        if not owns(fullname):
            return None
        relative = fullname.replace('.', '/')
        for suffix in ('/__init__.py', '.py'):
            name = relative + suffix
            entry = self.entries.get(name)
            if entry and entry['role'] == 'runtime':
                source = self.root / name
                loader = PayloadLoader(source, entry['sha256'])
                package = suffix.startswith('/')
                spec = importlib.util.spec_from_file_location(fullname, source, loader=loader,
                    submodule_search_locations=[str(source.parent)] if package else None)
                self.loaded[fullname] = (source, loader)
                return spec
        raise ModuleNotFoundError(f'SDK module is absent from the private payload: {fullname}')

    def verify_origins(self) -> dict[str, str]:
        result = {}
        for name, module in tuple(sys.modules.items()):
            if not owns(name):
                continue
            expected = self.loaded.get(name)
            spec = getattr(module, '__spec__', None)
            if expected is None or spec is None or spec.loader is not expected[1] or spec.origin != str(expected[0]) or getattr(module, '__file__', None) != str(expected[0]):
                raise ImportError('SDK module origin differs from the private payload')
            result[name] = str(expected[0])
        return result


def activate(root: Path) -> PayloadFinder:
    if any(owns(name) for name in sys.modules):
        raise ImportError('SDK namespace was loaded before isolated worker activation')
    manifest = verify(root)
    finder = PayloadFinder(root, manifest)
    sys.meta_path.insert(0, finder)
    return finder

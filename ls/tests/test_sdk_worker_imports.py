import hashlib
import importlib
from pathlib import Path
import sys
import types

import pytest

from ls.core.agent import sdk_imports


@pytest.fixture
def payload(tmp_path, monkeypatch):
    package = tmp_path / 'pydantic_ai'
    package.mkdir()
    (package / '__init__.py').write_text('VALUE = 42\n')
    (package / 'child.py').write_text('VALUE = 43\n')
    files = {str(p.relative_to(tmp_path)): {'role': 'runtime', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in package.iterdir()}
    monkeypatch.setattr(sdk_imports, 'verify', lambda root: {'files': files})
    before = list(sys.meta_path)
    yield tmp_path
    sys.meta_path[:] = before
    for name in list(sys.modules):
        if sdk_imports.owns(name):
            del sys.modules[name]


def test_payload_wins_over_ambient_package_and_checks_origins(payload, tmp_path, monkeypatch):
    ambient = tmp_path / 'ambient'
    (ambient / 'pydantic_ai').mkdir(parents=True)
    (ambient / 'pydantic_ai/__init__.py').write_text("raise AssertionError('ambient import')")
    monkeypatch.syspath_prepend(str(ambient))
    finder = sdk_imports.activate(payload)
    module = importlib.import_module('pydantic_ai')
    assert module.VALUE == 42
    assert importlib.import_module('pydantic_ai.child').VALUE == 43
    assert finder.verify_origins()['pydantic_ai'] == str(payload / 'pydantic_ai/__init__.py')
    module.__file__ = str(ambient / 'pydantic_ai/__init__.py')
    with pytest.raises(ImportError, match='origin'):
        finder.verify_origins()


def test_preloaded_sdk_is_refused(payload, monkeypatch):
    monkeypatch.setitem(sys.modules, 'pydantic_ai', types.ModuleType('pydantic_ai'))
    with pytest.raises(ImportError, match='before'):
        sdk_imports.activate(payload)


def test_changed_source_and_absent_module_are_refused(payload):
    sdk_imports.activate(payload)
    importlib.import_module('pydantic_ai')
    with pytest.raises(ModuleNotFoundError, match='absent'):
        importlib.import_module('pydantic_ai.substituted')
    (payload / 'pydantic_ai/child.py').write_text('VALUE = 0')
    with pytest.raises(ImportError, match='changed'):
        importlib.import_module('pydantic_ai.child')


def test_resource_loading_preserves_package_data(payload):
    from importlib.resources import files
    sdk_imports.activate(payload)
    importlib.import_module('pydantic_ai')
    assert 'VALUE = 43' in files('pydantic_ai').joinpath('child.py').read_text()

from contextlib import contextmanager
from pathlib import Path
import sys

import pytest

from ls.core.agent import registration_dispatch as dispatch, registration_owner as owner, registration_plan as plan


@pytest.fixture
def registered(tmp_path, monkeypatch):
    root = tmp_path / "protected runtime"
    release = root / ("a"*64)
    module = release / "venv/lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages/ls/core/agent/registered_cli.py"
    module.parent.mkdir(parents=True)
    module.write_bytes(Path(plan.__file__).with_name("registered_cli.py").read_bytes())
    @contextmanager
    def selected(actual, **kwargs):
        assert actual == root
        yield release
    for component in (owner, plan, dispatch):
        monkeypatch.setattr(component, "selected", selected)
    directory = tmp_path / "bin"
    specification = owner.plan(root, directory, path_env=str(directory))
    owner.apply(root, directory, specification["plan_sha256"], path_env=str(directory))
    return root, directory / owner.CLI_COMMAND, module


def test_resolves_canonical_argv_without_executing_registration(registered):
    root, executable, _ = registered
    before = {p.name: p.read_bytes() for p in executable.parent.iterdir()}
    argv = dispatch.resolve(executable, root)
    assert argv == plan.command(root, "a"*64)
    assert argv[0] != str(executable) and argv[1:4] == ["-I", "-B", "-m"]
    assert before == {p.name: p.read_bytes() for p in executable.parent.iterdir()}
    # Later edits cannot substitute the already resolved protected argv.
    executable.write_text("untrusted replacement")
    assert argv == plan.command(root, "a"*64)


@pytest.mark.parametrize("kind", ["modified", "pending", "receipt", "root", "dispatcher"])
def test_refuses_unqualified_registration(registered, kind):
    root, executable, module = registered
    if kind == "modified":
        executable.write_text("untrusted")
    elif kind == "pending":
        (executable.parent / owner.PENDING).write_text("{}")
        (executable.parent / owner.PENDING).chmod(0o600)
    elif kind == "receipt":
        receipt = executable.parent / owner.RECEIPT
        receipt.write_bytes(receipt.read_bytes()+b" ")
    elif kind == "root":
        root = root.parent / "another"
    elif kind == "dispatcher":
        module.write_text("untrusted")
    with pytest.raises(ValueError):
        dispatch.resolve(executable, root)


def test_stale_selection_refused(registered, monkeypatch):
    root, executable, _ = registered
    @contextmanager
    def selected(actual, **kwargs):
        yield root / ("b"*64)
    monkeypatch.setattr(dispatch, "selected", selected)
    with pytest.raises(ValueError, match="stale"):
        dispatch.resolve(executable, root)


def test_missing_registration_does_not_create_state(tmp_path):
    root, executable = tmp_path / "runtimes", tmp_path / "bin" / owner.CLI_COMMAND
    with pytest.raises(FileNotFoundError):
        dispatch.resolve(executable, root)
    assert not root.exists() and not executable.parent.exists()

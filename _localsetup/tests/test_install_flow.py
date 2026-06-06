import json
import io
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import _localsetup.core.apply as apply_mod
import _localsetup.core.cli as cli_mod
import _localsetup.core.conversion as conversion_mod
import _localsetup.core.wizard as wizard
from _localsetup.core.apply import apply_plan
from _localsetup.core.boundary import scan_tar_for_leaks
from _localsetup.core.cli import _split_csv
from _localsetup.core.config import InstallConfig, load_install_config, merge_cli_config
from _localsetup.core.context import build_agent_context, render_markdown_report
from _localsetup.core.conversion import convert_repo
from _localsetup.core.dependencies import ensure_dependencies
from _localsetup.core.doctor import run_doctor
from _localsetup.core.docs import generate_alias_outputs
from _localsetup.core.hooks import run_maintainer_gate
from _localsetup.core.lockfile import load_json
from _localsetup.core.migration import conservative_migrate, detect_legacy_artifacts, scan_legacy_references
from _localsetup.core.package import build_public_artifact, parse_sha256_file, verify_release_artifact
from _localsetup.core.plan import build_install_plan
from _localsetup.core.provenance import MARKER_JSON
from _localsetup.core.rollback import rollback
from _localsetup.core.repair import run_repair
from _localsetup.core.schema import validate_json_schema
from _localsetup.core.shell import detect_invocation_target, is_managed_shim, register_shell_command, shell_registration_status
from _localsetup.core.skills import skill_taxonomy_payload
from _localsetup.core.verify import verify_install
from _localsetup.core.wizard import Choice, TerminalWizard, choose_many, choose_many_checkbox, choose_one, run_wizard
from _localsetup.core.workflows import workflow_catalog_payload


class KeyboardInterruptStream(io.StringIO):
    def readline(self, *args: object, **kwargs: object) -> str:
        raise KeyboardInterrupt


class FakeTtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True


class FakeAsciiTtyStringIO(FakeTtyStringIO):
    @property
    def encoding(self) -> str:
        return "ascii"


class FakeKeyInput:
    def __init__(self, text: str) -> None:
        self.text = text
        self.offset = 0

    @property
    def remaining(self) -> bool:
        return self.offset < len(self.text)

    def read(self, size: int = 1) -> str:
        if not self.remaining:
            return ""
        value = self.text[self.offset : self.offset + size]
        self.offset += len(value)
        return value

    def fileno(self) -> int:
        return 0

    def isatty(self) -> bool:
        return True


def patch_fake_key_input(monkeypatch: pytest.MonkeyPatch, stream: FakeKeyInput) -> None:
    def fake_select(
        read_fds: list[int], write_fds: list[int], error_fds: list[int], timeout: float | None = None
    ) -> tuple[list[int], list[int], list[int]]:
        return (read_fds if stream.remaining else [], write_fds, error_fds)

    monkeypatch.setattr(wizard.select, "select", fake_select)


def enable_checkbox_key_mode(monkeypatch: pytest.MonkeyPatch, stream: FakeKeyInput) -> None:
    patch_fake_key_input(monkeypatch, stream)
    monkeypatch.setattr(wizard, "_can_use_checkbox_keys", lambda term: True)
    monkeypatch.setattr(wizard.termios, "tcgetattr", lambda fd: [])
    monkeypatch.setattr(wizard.termios, "tcsetattr", lambda fd, when, settings: None)
    monkeypatch.setattr(wizard.tty, "setcbreak", lambda fd: None)


def make_temp_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    (repo / "_localsetup").mkdir(parents=True)
    shutil.copytree(source / "_localsetup" / "config", repo / "_localsetup" / "config")
    shutil.copytree(source / "_localsetup" / "adapters", repo / "_localsetup" / "adapters")
    shutil.copytree(source / "_localsetup" / "core", repo / "_localsetup" / "core")
    shutil.copytree(source / "_localsetup" / "skills", repo / "_localsetup" / "skills")
    shutil.copytree(source / "_localsetup" / "workflows", repo / "_localsetup" / "workflows")
    shutil.copytree(source / "_localsetup" / "tools", repo / "_localsetup" / "tools")
    shutil.copy2(source / "VERSION", repo / "VERSION")
    shutil.copy2(source / "pyproject.toml", repo / "pyproject.toml")
    shutil.copy2(source / "uv.lock", repo / "uv.lock")
    shutil.copytree(source / "assets", repo / "assets")
    (repo / "_localsetup" / "docs" / "_generated").mkdir(parents=True)
    (repo / "_localsetup" / "docs" / "migration").mkdir(parents=True)
    for rel_path in ("README.md", "FEATURES.md", "PLATFORM_REGISTRY.md"):
        shutil.copy2(source / "_localsetup" / "docs" / rel_path, repo / "_localsetup" / "docs" / rel_path)
    (repo / ".github").mkdir()
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    return repo


def assert_scoped_adapter(path: Path, *packages: str) -> None:
    assert path.is_dir()
    assert not path.is_symlink()
    assert (path / ".localsetup-adapter.json").is_file()
    for package in packages:
        assert (path / package).is_symlink() or (path / package).is_dir()

def make_bootstrap_git_repo(tmp_path: Path) -> Path:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    shutil.copytree(source / "_localsetup", repo / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    shutil.copy2(source / "VERSION", repo / "VERSION")
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "init"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    return repo


def make_bootstrap_git_repo_with_legacy_commit(tmp_path: Path) -> tuple[Path, str, str]:
    source = Path(__file__).resolve().parents[2]
    repo = tmp_path / "repo"
    marker = repo / "_localsetup" / "README.md"
    marker.parent.mkdir(parents=True)
    marker.write_text("# Localsetup\n", encoding="utf-8")
    shutil.copy2(source / "VERSION", repo / "VERSION")
    (repo / "README.md").write_text("# Localsetup\n", encoding="utf-8")
    (repo / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "legacy"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    legacy_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    shutil.rmtree(repo / "_localsetup")
    shutil.copytree(source / "_localsetup", repo / "_localsetup", ignore=shutil.ignore_patterns("__pycache__", ".cache"))
    subprocess.run(["git", "add", "."], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "current"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return repo, legacy_commit, current_commit


def make_bootstrap_git_repo_with_release_tags(tmp_path: Path) -> tuple[Path, str, str]:
    repo = make_bootstrap_git_repo(tmp_path)
    subprocess.run(["git", "tag", "v4.8.7"], cwd=repo, text=True, capture_output=True, check=True)
    (repo / "README.md").write_text("# Localsetup\n\nrelease refresh\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Localsetup Test", "-c", "user.email=test@example.invalid", "commit", "-m", "release"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    subprocess.run(["git", "tag", "v4.8.9"], cwd=repo, text=True, capture_output=True, check=True)
    subprocess.run(["git", "tag", "v4.9.0-rc.1"], cwd=repo, text=True, capture_output=True, check=True)
    old_commit = subprocess.run(
        ["git", "rev-list", "-n", "1", "v4.8.7"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    return repo, old_commit, current_commit


def run_installer_in_pty(
    command: list[str],
    *,
    input_text: str,
    cwd: Path,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    script = shutil.which("script")
    if script is None:
        pytest.skip("script command is required for pseudo-terminal installer tests")
    log_path = cwd / "installer-pty.log"
    shell_command = " ".join(shlex.quote(part) for part in command)
    effective_env = {
        **os.environ,
        "LOCALSETUP_WIZARD_SELECTION_MODE": "line",
        "LOCALSETUP_WIZARD_DETAIL": "compact",
        **(env or {}),
    }
    return subprocess.run(
        [script, "-q", "-e", "-c", shell_command, str(log_path)],
        input=input_text,
        cwd=cwd,
        env=effective_env,
        text=True,
        capture_output=True,
        check=False,
    )

def run_localsetup_cli(root: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(root / "_localsetup" / "tools" / "localsetup.py"),
            "--source-root",
            str(root),
            "--home",
            str(home),
            *args,
        ],
        text=True,
        capture_output=True,
        check=False,
    )

__all__ = [name for name in globals() if not name.startswith("__")]

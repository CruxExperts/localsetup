from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from ls.core.cli import main
from ls.core.client_state import locator


ROOT = Path(__file__).resolve().parents[2]


def repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@localsetup.invalid"], check=True)
    (path / "tracked").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "tracked"], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-qm", "fixture"], check=True)
    return path


def invoke(capsys, *args: str) -> tuple[int, dict]:
    result = main(["--source-root", str(ROOT), *args])
    output = capsys.readouterr()
    return result, json.loads(output.out) if output.out else {"stderr": output.err}


def allocation_args() -> list[str]:
    return [
        "--purpose", "handoff", "--extension", "md", "--kind", "restart-artifact",
        "--schema", "restart-v1", "--producer", "controller",
    ]


def test_state_path_is_read_only_until_apply(tmp_path: Path, capsys) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(repo)
    )
    assert code == 0 and payload["exclude"]["action"] == "append"
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    assert "/.codex/state/" not in exclude.read_text(encoding="utf-8")

    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(repo), "--apply-exclude"
    )
    assert code == 0 and payload["exclude"]["action"] == "applied"


def test_state_allocate_and_verify_cli(tmp_path: Path, capsys) -> None:
    repo = repository(tmp_path / "repo")
    content = tmp_path / "payload.md"
    content.write_text("restart\n", encoding="utf-8")
    code, allocated = invoke(
        capsys,
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        "--agent", "controller", "--purpose", "restart-handoff", "--extension", "md",
        "--kind", "restart-artifact", "--schema", "restart-v1", "--producer", "controller",
        "--consumer", "codex", "--content-file", str(content),
    )
    assert code == 0 and allocated["ok"]
    assert str(repo) not in json.dumps(allocated)

    code, verified = invoke(
        capsys,
        "state", "verify", "--client", "codex/codex-cli", "--directory", str(repo),
        "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]

    (repo / ".codex" / "state" / allocated["artifact"]).write_text("changed\n", encoding="utf-8")
    code, verified = invoke(
        capsys,
        "state", "verify", "--client", "codex/codex-cli", "--directory", str(repo),
        "--artifact", allocated["artifact"],
    )
    assert code == 1 and not verified["ok"]


def test_top_level_target_drives_path_allocate_and_verify_without_wrong_target_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = repository(tmp_path / "target")
    wrong = repository(tmp_path / "wrong")
    monkeypatch.chdir(wrong)
    prefix = ("--target-directory", str(target), "state")

    code, path_payload = invoke(capsys, *prefix, "path", "--client", "codex/codex-cli")
    assert code == 0 and path_payload["scope"] == "repo"

    code, allocated = invoke(
        capsys, *prefix, "allocate", "--client", "codex/codex-cli", *allocation_args()
    )
    assert code == 0 and allocated["ok"]
    assert (target / ".codex" / "state" / allocated["artifact"]).is_file()
    assert not (wrong / ".codex" / "state").exists()

    code, verified = invoke(
        capsys, *prefix, "verify", "--client", "codex/codex-cli",
        "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]


def test_explicit_state_directory_precedes_top_level_target_including_dot(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = repository(tmp_path / "explicit")
    target = repository(tmp_path / "target")
    monkeypatch.chdir(explicit)
    code, payload = invoke(
        capsys, "--target-directory", str(target), "state", "path",
        "--client", "codex/codex-cli", "--directory", ".", "--apply-exclude",
    )
    assert code == 0 and payload["scope"] == "repo"
    assert payload["exclude"]["action"] == "applied"
    explicit_exclude = explicit / ".git" / "info" / "exclude"
    target_exclude = target / ".git" / "info" / "exclude"
    assert "/.codex/state/" in explicit_exclude.read_text(encoding="utf-8")
    assert "/.codex/state/" not in target_exclude.read_text(encoding="utf-8")


@pytest.mark.parametrize("value", ["", "   "])
def test_empty_codex_home_cli_fails_without_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    monkeypatch.chdir(plain)
    monkeypatch.setenv("CODEX_HOME", value)
    code, payload = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--scope", "global", "--directory", str(plain), *allocation_args(),
    )
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_environment", "message": "CODEX_HOME must be a non-empty absolute path"},
        "ok": False,
    }
    assert not (plain / "state").exists()


def test_fifo_content_is_rejected_promptly_without_mutation(tmp_path: Path) -> None:
    repo = repository(tmp_path / "repo")
    fifo = tmp_path / "content.fifo"
    fifo.parent.mkdir(exist_ok=True)
    fifo.unlink(missing_ok=True)
    os.mkfifo(fifo)
    command = [
        sys.executable, str(ROOT / "ls" / "tools" / "localsetup.py"),
        "--source-root", str(ROOT), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), *allocation_args(), "--content-file", str(fifo),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, timeout=3, check=False)
    payload = json.loads(completed.stdout)
    assert completed.returncode == 2 and payload["error"]["code"] == "invalid_content"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


@pytest.mark.parametrize("field", ["predecessor", "checkpoint"])
def test_oversized_relative_metadata_cli_rejects_without_mutation(
    tmp_path: Path, capsys, field: str
) -> None:
    repo = repository(tmp_path / "repo")
    code, payload = invoke(
        capsys, "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), *allocation_args(), f"--{field}", "a" * 513,
    )
    assert code == 2 and payload["error"]["code"] == f"invalid_{field}"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_oversized_metadata_cli_rejects_without_mutation(
    tmp_path: Path, capsys
) -> None:
    repo = repository(tmp_path / "repo")
    args = [
        "state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo),
        *allocation_args(),
    ]
    for index in reversed(range(18000)):
        args.extend(["--consumer", f"c{index:05d}-" + ("a" * 55)])
    code, payload = invoke(capsys, *args)
    assert code == 2 and payload["error"]["code"] == "invalid_metadata"
    assert not (repo / ".codex" / "state").exists()
    assert "/.codex/state/" not in (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")


def test_explicit_global_scope_ignores_missing_directory_for_path_allocate_verify(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.delenv("CODEX_HOME", raising=False)
    prefix = (
        "--home", str(home), "state", "path", "--client", "codex/codex-cli",
        "--scope", "global", "--directory", str(missing),
    )
    code, payload = invoke(capsys, *prefix)
    assert code == 0 and payload["scope"] == "global"
    code, allocated = invoke(
        capsys, "--home", str(home), "state", "allocate", "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(missing), *allocation_args(),
    )
    assert code == 0 and allocated["ok"]
    code, verified = invoke(
        capsys, "--home", str(home), "state", "verify", "--client", "codex/codex-cli", "--scope", "global",
        "--directory", str(missing), "--artifact", allocated["artifact"],
    )
    assert code == 0 and verified["ok"]


@pytest.mark.parametrize("action", ["path", "allocate", "verify"])
@pytest.mark.parametrize("target_kind", ["missing", "file", "permission"])
def test_invalid_target_has_stable_sanitized_json_and_no_mutation(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch, action: str, target_kind: str
) -> None:
    target = tmp_path / "private-invalid-target"
    if target_kind == "file":
        target.write_text("not a directory\n", encoding="utf-8")
    elif target_kind == "permission":
        original_resolve = Path.resolve

        def deny_resolve(path: Path, *args, **kwargs):
            if path == target:
                raise PermissionError("private permission detail")
            return original_resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", deny_resolve)
    args = ["state", action, "--client", "codex/codex-cli", "--directory", str(target)]
    if action == "allocate":
        args.extend(allocation_args())
    elif action == "verify":
        args.extend(["--artifact", "codex-20260715T000000000Z-handoff.md"])
    code, payload = invoke(capsys, *args)
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_directory", "message": "state probe directory is unavailable"},
        "ok": False,
    }
    assert str(target) not in json.dumps(payload)
    assert not (tmp_path / ".codex" / "state").exists()


def test_deleted_default_cwd_has_stable_sanitized_json_and_no_mutation(tmp_path: Path) -> None:
    deleted = tmp_path / "private-deleted-cwd"
    deleted.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    script = (
        "import os,sys; "
        "dead,tool,root,home=sys.argv[1:]; "
        "os.chdir(dead); os.rmdir(dead); "
        "os.execv(sys.executable,[sys.executable,tool,'--source-root',root,'--home',home,"
        "'state','path','--client','codex/codex-cli'])"
    )
    completed = subprocess.run(
        [
            sys.executable, "-c", script, str(deleted),
            str(ROOT / "ls" / "tools" / "localsetup.py"), str(ROOT), str(home),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(completed.stdout)
    assert completed.returncode == 2
    assert payload == {
        "error": {"code": "invalid_directory", "message": "state probe directory is unavailable"},
        "ok": False,
    }
    combined = completed.stdout + completed.stderr
    assert str(deleted) not in combined and "Traceback" not in combined
    assert not (home / ".codex" / "state").exists()


def test_state_cli_rejects_unknown_client_without_traceback(tmp_path: Path, capsys) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    code, payload = invoke(
        capsys, "state", "path", "--client", "unknown/unknown-cli", "--directory", str(plain)
    )
    assert code == 2
    assert payload == {
        "error": {"code": "invalid_client", "message": "unknown or invalid client variant"},
        "ok": False,
    }


@pytest.mark.parametrize(
    "replacement",
    [
        ("--agent", "Bad Agent"),
        ("--purpose", "../private"),
        ("--extension", "md.exe"),
        ("--kind", "Bad Kind"),
        ("--schema", "Bad Schema"),
        ("--producer", "Bad Producer"),
        ("--predecessor", "C:/private"),
        ("--checkpoint", "..\\private"),
        ("--consumer", "Bad Consumer"),
        ("--content-file", "/private/missing-payload"),
    ],
)
def test_allocate_prevalidation_never_mutates_exclude_or_state(
    tmp_path: Path, capsys, replacement: tuple[str, str]
) -> None:
    repo = repository(tmp_path / "repo")
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    before = exclude.read_bytes()
    options = {
        "--agent": "controller", "--purpose": "handoff", "--extension": "md",
        "--kind": "restart-artifact", "--schema": "restart-v1", "--producer": "controller",
    }
    options[replacement[0]] = replacement[1]
    args = ["state", "allocate", "--client", "codex/codex-cli", "--directory", str(repo)]
    for key, value in options.items():
        args.extend([key, value])
    code, payload = invoke(capsys, *args)
    assert code == 2 and payload["ok"] is False
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


def test_missing_metadata_schema_fails_before_exclude_mutation(tmp_path: Path, capsys) -> None:
    source = tmp_path / "source"
    config = source / "ls" / "config"
    config.mkdir(parents=True)
    shutil.copy2(ROOT / "ls" / "config" / "clients.yaml", config / "clients.yaml")
    shutil.copy2(ROOT / "ls" / "config" / "clients.schema.json", config / "clients.schema.json")
    repo = repository(tmp_path / "repo")
    exclude = Path(subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-path", "info/exclude"],
        check=True, capture_output=True, text=True,
    ).stdout.strip())
    before = exclude.read_bytes()
    code = main([
        "--source-root", str(source), "state", "allocate", "--client", "codex/codex-cli",
        "--directory", str(repo), "--purpose", "handoff", "--extension", "md",
        "--kind", "restart-artifact", "--schema", "restart-v1", "--producer", "controller",
    ])
    payload = json.loads(capsys.readouterr().out)
    assert code == 2 and payload["error"]["code"] == "invalid_metadata_schema"
    assert exclude.read_bytes() == before
    assert not (repo / ".codex" / "state").exists()


def test_cli_sanitizes_injected_private_git_failure(
    tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = tmp_path / "private-home" / "secret-repo"
    plain.mkdir(parents=True)
    private = str(plain)
    failure = subprocess.CompletedProcess(["git"], 2, "", f"fatal: credential TOKEN at {private}")
    monkeypatch.setattr(locator, "_git", lambda *_args: failure)
    code, payload = invoke(
        capsys, "state", "path", "--client", "codex/codex-cli", "--directory", str(plain)
    )
    encoded = json.dumps(payload, sort_keys=True)
    assert code == 2
    assert payload == {
        "error": {"code": "git_probe_failed", "message": "ambiguous Git worktree probe failure"},
        "ok": False,
    }
    assert private not in encoded and "TOKEN" not in encoded

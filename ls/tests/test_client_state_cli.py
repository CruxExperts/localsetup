from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess

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

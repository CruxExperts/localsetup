from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest
import yaml

from ls.core.domain_shapes import compiler as domain_compiler
from ls.core.cli import main
from ls.core.domain_shapes import (
    DomainCompileError,
    DomainConfigError,
    canonical_json_bytes,
    compile_domain,
    load_domain_shapes,
)

SCHEMA = Path(__file__).parents[1] / "config" / "domain-shapes.schema.json"


def _write_config(tmp_path: Path, *domains: dict) -> Path:
    if not (tmp_path / ".git").exists():
        subprocess.run(["git", "init", "--quiet", str(tmp_path)], check=True)
    path = tmp_path / "domains.yaml"
    path.write_text(
        yaml.safe_dump({"schema_version": 1, "domains": list(domains)}, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _domain(domain_id: str = "test", **overrides) -> dict:
    value = {
        "id": domain_id,
        "roots": [{"kind": "tree", "path": "src"}],
        "include": {"glob": [], "regex": []},
        "exclude": {"glob": [], "regex": []},
        "max_files": 100,
        "max_bytes": 1_000_000,
    }
    value.update(overrides)
    return value


def test_file_tree_and_multi_root_selection_is_portable_and_sorted(tmp_path: Path) -> None:
    (tmp_path / "single.txt").write_text("one", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "a.txt").write_text("aa", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[
                {"kind": "file", "path": "single.txt"},
                {"kind": "tree", "path": "src"},
                {"kind": "tree", "path": "src"},
            ]
        ),
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert [item["path"] for item in result["selected"]] == [
        "single.txt",
        "src/nested/a.txt",
        "src/z.txt",
    ]
    assert all(set(item) == {"path", "sha256", "size"} for item in result["selected"])
    assert all(len(item["sha256"]) == 64 for item in result["selected"])


def test_glob_and_regex_includes_and_excludes_are_applied(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "nested").mkdir()
    (tmp_path / "src" / "nested" / "private.py").write_text("private", encoding="utf-8")
    for name in ("a.py", "b.py", "c.py", "skip.py", "note.txt"):
        (tmp_path / "src" / name).write_text(name, encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            include={"glob": ["src/*.py"], "regex": [r"never-matches"]},
            exclude={"glob": ["src/skip.py"], "regex": [r"/c\.py$"]},
        ),
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert [item["path"] for item in result["selected"]] == ["src/a.py", "src/b.py"]
    reasons = {item["path"]: item["reason"] for item in result["excluded"]}
    assert reasons["src/c.py"] == "exclude_regex"
    assert reasons["src/skip.py"] == "exclude_glob"
    assert reasons["src/note.txt"] == "not_included"
    assert reasons["src/nested/private.py"] == "not_included"


def test_deny_rules_precede_user_allow_rules(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (tmp_path / ".localsetup-maint").mkdir()
    (tmp_path / ".localsetup-maint" / "private.txt").write_text("private", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / ".env").write_text("secret", encoding="utf-8")
    (tmp_path / "deploy.pem").write_text("secret", encoding="utf-8")
    (tmp_path / "allowed.txt").write_text("allowed", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert "allowed.txt" in {item["path"] for item in result["selected"]}
    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".localsetup-maint/private.txt" not in reported_paths
    assert "ignored.txt" not in reported_paths
    assert ".env" not in reported_paths
    assert "deploy.pem" not in reported_paths


def test_git_ignore_unavailability_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a", encoding="utf-8")
    config = _write_config(tmp_path, _domain())
    monkeypatch.setattr(domain_compiler.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("missing git")))

    with pytest.raises(DomainCompileError, match="Git ignore"):
        compile_domain(config, "test", tmp_path, schema_path=SCHEMA)


def test_symlink_entries_are_excluded_without_following_escape(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    outside = tmp_path.parent / "outside-domain.txt"
    outside.write_text("outside", encoding="utf-8")
    (tmp_path / "src" / "escape.txt").symlink_to(outside)
    config = _write_config(tmp_path, _domain())

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert all(item["path"] != "src/escape.txt" for item in result["selected"])
    assert {"path": "src/escape.txt", "reason": "symlink"} in result["excluded"]

    root_link = tmp_path / "linked-root"
    root_link.symlink_to(tmp_path / "src", target_is_directory=True)
    root_config = _write_config(
        tmp_path,
        _domain(roots=[{"kind": "tree", "path": "linked-root"}]),
    )
    with pytest.raises(DomainCompileError, match="symlink_root"):
        compile_domain(root_config, "test", tmp_path, schema_path=SCHEMA)

    repo_link = tmp_path.parent / "linked-repository"
    repo_link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(DomainCompileError, match="symlink component"):
        compile_domain(config, "test", repo_link, schema_path=SCHEMA)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("roots", [{"kind": "other", "path": "src"}], "not one of"),
        ("roots", [{"kind": "tree", "path": "/outside"}], "repo-relative"),
        ("roots", [{"kind": "tree", "path": "../outside"}], "parent"),
        ("roots", [{"kind": "tree", "path": "bad\x00path"}], "NUL"),
        ("exclude", {"glob": [], "regex": ["["]}, "invalid"),
    ],
)
def test_invalid_roots_and_regex_are_actionable(
    tmp_path: Path,
    field: str,
    value,
    message: str,
) -> None:
    domain = _domain(**{field: value})
    config = _write_config(tmp_path, domain)

    with pytest.raises(DomainConfigError, match=message):
        load_domain_shapes(config, schema_path=SCHEMA)


def test_duplicate_ids_and_unknown_fields_are_rejected(tmp_path: Path) -> None:
    duplicate = _write_config(tmp_path, _domain("same"), _domain("same"))
    with pytest.raises(DomainConfigError, match="duplicates"):
        load_domain_shapes(duplicate, schema_path=SCHEMA)

    unknown = _write_config(tmp_path, _domain(unknown=True))
    with pytest.raises(DomainConfigError, match="Additional properties"):
        load_domain_shapes(unknown, schema_path=SCHEMA)


def test_missing_root_and_budgets_fail_before_success(tmp_path: Path) -> None:
    missing = _write_config(
        tmp_path,
        _domain(roots=[{"kind": "tree", "path": "missing"}]),
    )
    with pytest.raises(DomainCompileError, match="missing_root"):
        compile_domain(missing, "test", tmp_path, schema_path=SCHEMA)

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("123", encoding="utf-8")
    limited = _write_config(tmp_path, _domain(max_files=0, max_bytes=1))
    with pytest.raises(DomainCompileError, match="max_files"):
        compile_domain(limited, "test", tmp_path, schema_path=SCHEMA)

    limited = _write_config(tmp_path, _domain(max_files=10, max_bytes=1))
    with pytest.raises(DomainCompileError, match="max_bytes"):
        compile_domain(limited, "test", tmp_path, schema_path=SCHEMA)


def test_unchanged_compiles_have_identical_bytes_and_digest(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("stable", encoding="utf-8")
    config = _write_config(tmp_path, _domain())

    first = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)
    second = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert first.output_bytes == second.output_bytes
    assert first.digest == second.digest
    without_digest = {key: value for key, value in first.items() if key != "digest"}
    assert hashlib.sha256(canonical_json_bytes(without_digest)).hexdigest() == first.digest
    (tmp_path / "src" / "a.txt").write_text("change", encoding="utf-8")
    changed = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)
    assert changed.digest != first.digest


def test_domain_cli_validate_compile_and_actionable_failure(tmp_path: Path, capsys) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("a", encoding="utf-8")
    config = _write_config(tmp_path, _domain())

    assert main(["domain", "validate", "--config", str(config)]) == 0
    validate_payload = json.loads(capsys.readouterr().out)
    assert validate_payload == {"domains": ["test"], "ok": True, "schema_version": 1}

    assert main(
        [
            "domain",
            "compile",
            "--config",
            str(config),
            "--domain",
            "test",
            "--directory",
            str(tmp_path),
        ]
    ) == 0
    compile_payload = json.loads(capsys.readouterr().out)
    assert compile_payload["selected"] == [
        {
            "path": "src/a.txt",
            "sha256": hashlib.sha256(b"a").hexdigest(),
            "size": 1,
        }
    ]
    assert compile_payload["digest"]

    assert main(
        [
            "domain",
            "compile",
            "--config",
            str(config),
            "--domain",
            "missing",
            "--directory",
            str(tmp_path),
        ]
    ) == 1
    error_payload = json.loads(capsys.readouterr().out)
    assert error_payload["ok"] is False
    assert "unknown domain" in error_payload["error"]

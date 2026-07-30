from __future__ import annotations

import hashlib
import json
from pathlib import Path
import os
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
    (tmp_path / ".gitignore").write_text(".codex/\n.omp/\nignored.txt\ntracked-ignored.txt\n", encoding="utf-8")
    (tmp_path / ".localsetup-maint").mkdir()
    (tmp_path / ".localsetup-maint" / "private.txt").write_text("private", encoding="utf-8")
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "cache.txt").write_text("private", encoding="utf-8")
    (tmp_path / "ignored.txt").write_text("ignored", encoding="utf-8")
    (tmp_path / "tracked-ignored.txt").write_text("tracked", encoding="utf-8")
    adapter_skill = tmp_path / ".codex" / "skills" / "custom" / "SKILL.md"
    adapter_skill.parent.mkdir(parents=True)
    adapter_skill.write_text("tracked adapter", encoding="utf-8")
    private_run = tmp_path / ".codex" / "runs" / "private.txt"
    private_run.parent.mkdir(parents=True)
    private_run.write_text("private", encoding="utf-8")
    codex_runtime = tmp_path / ".codex" / "auth.json"
    codex_runtime.write_text("credential", encoding="utf-8")
    omp_skill = tmp_path / ".omp" / "skills" / "custom" / "SKILL.md"
    omp_skill.parent.mkdir(parents=True)
    omp_skill.write_text("tracked adapter", encoding="utf-8")
    omp_runtime = tmp_path / ".omp" / "config.yml"
    omp_runtime.write_text("runtime", encoding="utf-8")
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
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "-f",
            "tracked-ignored.txt",
            ".codex/skills/custom/SKILL.md",
            ".omp/skills/custom/SKILL.md",
        ],
        check=True,
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert "allowed.txt" in {item["path"] for item in result["selected"]}
    assert "tracked-ignored.txt" in {item["path"] for item in result["selected"]}
    assert ".codex/skills/custom/SKILL.md" in {item["path"] for item in result["selected"]}
    assert ".omp/skills/custom/SKILL.md" in {item["path"] for item in result["selected"]}
    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".localsetup-maint/private.txt" not in reported_paths
    assert ".codex/runs/private.txt" not in reported_paths
    assert ".agents/state/private.txt" not in reported_paths
    assert ".codex/auth.json" not in reported_paths
    assert ".omp/config.yml" not in reported_paths
    assert ".pytest_cache/cache.txt" not in reported_paths
    assert "ignored.txt" not in reported_paths
    assert ".env" not in reported_paths
    assert "deploy.pem" not in reported_paths


@pytest.mark.parametrize(
    "adapter_root",
    [".agents", ".claude", ".cursor", ".kilo", ".openclaw", ".opencode"],
)
def test_supported_adapter_roots_select_only_tracked_skills(tmp_path: Path, adapter_root: str) -> None:
    (tmp_path / ".gitignore").write_text(f"{adapter_root}/\n", encoding="utf-8")
    skill = tmp_path / adapter_root / "skills" / "custom" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("tracked adapter", encoding="utf-8")
    untracked_skill = tmp_path / adapter_root / "skills" / "untracked" / "SKILL.md"
    untracked_skill.parent.mkdir(parents=True)
    untracked_skill.write_text("untracked adapter", encoding="utf-8")
    runtime = tmp_path / adapter_root / "settings.local.json"
    runtime.write_text("private runtime", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "-f",
            f"{adapter_root}/skills/custom/SKILL.md",
            f"{adapter_root}/settings.local.json",
        ],
        check=True,
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    selected_paths = {item["path"] for item in result["selected"]}
    reported_paths = selected_paths | {item["path"] for item in result["excluded"]}
    assert f"{adapter_root}/skills/custom/SKILL.md" in selected_paths
    assert f"{adapter_root}/settings.local.json" not in reported_paths
    assert f"{adapter_root}/skills/untracked/SKILL.md" not in reported_paths


def test_tracked_runtime_file_does_not_open_adapter_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(".codex/\n", encoding="utf-8")
    runtime = tmp_path / ".codex"
    runtime.mkdir()
    (runtime / "auth.json").write_text("private", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", ".codex/auth.json"], check=True)
    original_scandir = domain_compiler.os.scandir

    def guarded_scandir(path: Path | str):
        if Path(path) == runtime:
            raise AssertionError("runtime directory was traversed")
        return original_scandir(path)

    monkeypatch.setattr(domain_compiler.os, "scandir", guarded_scandir)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".codex/auth.json" not in reported_paths


def test_private_directory_below_tracked_adapter_is_pruned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text(".codex/\n", encoding="utf-8")
    private = tmp_path / ".codex" / "skills" / "custom" / ".CACHE"
    private.mkdir(parents=True)
    tracked = private / "tracked.txt"
    tracked.write_text("private", encoding="utf-8")
    private_filename_directory = tmp_path / ".codex" / "skills" / "custom" / ".env"
    private_filename_directory.mkdir()
    (private_filename_directory / "tracked.txt").write_text("private", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(tmp_path),
            "add",
            "-f",
            ".codex/skills/custom/.CACHE/tracked.txt",
            ".codex/skills/custom/.env/tracked.txt",
        ],
        check=True,
    )
    original_scandir = domain_compiler.os.scandir

    def guarded_scandir(path: Path | str):
        if Path(path) == private:
            raise AssertionError("private adapter directory was traversed")
        return original_scandir(path)

    monkeypatch.setattr(domain_compiler.os, "scandir", guarded_scandir)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".codex/skills/custom/.CACHE/tracked.txt" not in reported_paths
    assert ".codex/skills/custom/.env/tracked.txt" not in reported_paths


def test_gitlink_index_mode_cannot_select_replacement_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    replacement = tmp_path / ".codex" / "skills" / "vendor"
    replacement.parent.mkdir(parents=True)
    replacement.write_text("not tracked by the superproject", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    monkeypatch.setattr(
        domain_compiler,
        "_git_tracked_paths",
        lambda _repo_root: {".codex/skills/vendor": 0o160000},
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".codex/skills/vendor" not in reported_paths


def test_intent_to_add_adapter_file_is_not_selected(tmp_path: Path) -> None:
    adapter = tmp_path / ".codex" / "skills" / "custom"
    adapter.mkdir(parents=True)
    (adapter / "leak.txt").write_text("not in the index", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-N", "-f", ".codex/skills/custom/leak.txt"],
        check=True,
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".codex/skills/custom/leak.txt" not in reported_paths


def test_hard_linked_adapter_file_is_not_selected(tmp_path: Path) -> None:
    runtime = tmp_path / ".codex" / "auth.json"
    runtime.parent.mkdir(parents=True)
    runtime.write_text("private", encoding="utf-8")
    adapter = tmp_path / ".codex" / "skills" / "custom" / "SKILL.md"
    adapter.parent.mkdir(parents=True)
    try:
        os.link(runtime, adapter)
    except OSError:
        pytest.skip("filesystem does not support hard links")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "-f", ".codex/skills/custom/SKILL.md"], check=True)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    reported_paths = {item["path"] for item in result["selected"]} | {
        item["path"] for item in result["excluded"]
    }
    assert ".codex/skills/custom/SKILL.md" not in reported_paths


def test_git_ignored_untracked_directories_are_pruned_before_recursion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / ".gitignore").write_text("ignored-output/\n", encoding="utf-8")
    ignored = tmp_path / "ignored-output"
    ignored.mkdir()
    (ignored / "generated.txt").write_text("generated", encoding="utf-8")
    (tmp_path / "allowed.txt").write_text("allowed", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    original_scandir = domain_compiler.os.scandir

    def guarded_scandir(path: Path | str):
        if Path(path) == ignored:
            raise AssertionError("ignored directory was traversed")
        return original_scandir(path)

    monkeypatch.setattr(domain_compiler.os, "scandir", guarded_scandir)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    selected_paths = {item["path"] for item in result["selected"]}
    assert "allowed.txt" in selected_paths
    assert not any(path.startswith("ignored-output/") for path in selected_paths)


def test_git_ignored_directory_with_tracked_descendant_is_traversed(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("ignored-mixed/\n", encoding="utf-8")
    mixed = tmp_path / "ignored-mixed"
    mixed.mkdir()
    (mixed / "tracked.txt").write_text("tracked", encoding="utf-8")
    (mixed / "generated.txt").write_text("generated", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", "ignored-mixed/tracked.txt"],
        check=True,
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    selected_paths = {item["path"] for item in result["selected"]}
    assert "ignored-mixed/tracked.txt" in selected_paths
    assert "ignored-mixed/generated.txt" not in selected_paths


def test_case_distinct_ignored_directory_does_not_prune_tracked_sibling(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("cache/\n", encoding="utf-8")
    ignored = tmp_path / "cache"
    ignored.mkdir()
    try:
        tracked_directory = tmp_path / "CACHE"
        tracked_directory.mkdir()
    except FileExistsError:
        pytest.skip("filesystem is case-insensitive")
    (ignored / "generated.txt").write_text("generated", encoding="utf-8")
    (tracked_directory / "tracked.txt").write_text("tracked", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "CACHE/tracked.txt"], check=True)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    selected_paths = {item["path"] for item in result["selected"]}
    assert "CACHE/tracked.txt" in selected_paths
    assert "cache/generated.txt" not in selected_paths


def test_posix_backslash_index_path_cannot_authorize_adapter_path(tmp_path: Path) -> None:
    if os.sep == "\\":
        pytest.skip("POSIX-only filename behavior")
    literal = ".codex\\skills\\tracked.txt"
    (tmp_path / literal).write_text("tracked literal name", encoding="utf-8")
    adapter = tmp_path / ".codex" / "skills"
    adapter.mkdir(parents=True)
    (adapter / "tracked.txt").write_text("untracked adapter", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", literal], check=True)

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    selected_paths = {item["path"] for item in result["selected"]}
    assert literal in selected_paths
    assert ".codex/skills/tracked.txt" not in selected_paths


def test_root_beginning_with_pathspec_magic_is_literal(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text(":literal/\n", encoding="utf-8")
    root = tmp_path / ":literal"
    root.mkdir()
    (root / "tracked.txt").write_text("tracked", encoding="utf-8")
    (root / "generated.txt").write_text("generated", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(roots=[{"kind": "tree", "path": ":literal"}]),
    )
    subprocess.run(
        ["git", "--literal-pathspecs", "-C", str(tmp_path), "add", "-f", ":literal/tracked.txt"],
        check=True,
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert [item["path"] for item in result["selected"]] == [":literal/tracked.txt"]


def test_non_utf8_filename_has_stable_json_encoding(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    filename = os.fsdecode(b"non-utf8-\xff.txt")
    if "\udcff" not in filename:
        pytest.skip("filesystem encoding does not use surrogateescape")
    (tmp_path / filename).write_text("content", encoding="utf-8")
    config = _write_config(
        tmp_path,
        _domain(
            roots=[{"kind": "tree", "path": "."}],
            include={"glob": ["**/*"], "regex": []},
        ),
    )

    result = compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    assert filename in {item["path"] for item in result["selected"]}
    assert b"non-utf8-\\udcff.txt" in result.output_bytes
    assert (
        main(
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
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "\\udcff" in output
    assert filename in {item["path"] for item in json.loads(output)["selected"]}


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


def test_unreadable_tree_and_over_budget_files_fail_before_content_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.txt").write_text("123", encoding="utf-8")
    config = _write_config(tmp_path, _domain())

    def unreadable_scandir(_path: Path):
        raise OSError("permission denied")

    monkeypatch.setattr(domain_compiler.os, "scandir", unreadable_scandir)
    with pytest.raises(DomainCompileError, match="could not enumerate"):
        compile_domain(config, "test", tmp_path, schema_path=SCHEMA)

    monkeypatch.undo()
    monkeypatch.setattr(
        domain_compiler,
        "_content_digest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("content digest")),
    )
    limited = _write_config(tmp_path, _domain(max_files=0, max_bytes=100))
    with pytest.raises(DomainCompileError, match="max_files"):
        compile_domain(limited, "test", tmp_path, schema_path=SCHEMA)

    monkeypatch.undo()
    monkeypatch.setattr(
        domain_compiler.os,
        "read",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("content read")),
    )
    with pytest.raises(DomainCompileError, match="max_bytes"):
        domain_compiler._content_digest(tmp_path / "src" / "a.txt", max_bytes=1)


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

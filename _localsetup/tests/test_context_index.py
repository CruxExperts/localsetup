from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL = REPO_ROOT / "_localsetup" / "tools" / "context_index.py"
LOCALSETUP = REPO_ROOT / "_localsetup" / "tools" / "localsetup.py"


def run_context(repo: Path, home: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(TOOL), "--repo", str(repo), "--home", str(home), *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    return json.loads(completed.stdout)


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    home = tmp_path / "home"
    repo.mkdir()
    home.mkdir()
    (repo / "README.md").write_text(
        "# Localsetup Demo\n\nInstall workflow context and vector search memory live here.\n",
        encoding="utf-8",
    )
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text(
        "def run_workflow():\n    return 'context index vector workflow'\n",
        encoding="utf-8",
    )
    (repo / ".env").write_text("OPENAI_API_KEY=sk-test-secret\n", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "noise.js").write_text("secret token noise\n", encoding="utf-8")
    return repo, home


def test_context_index_schema_has_native_indexes_for_common_searches(tmp_path: Path) -> None:
    repo, home = make_repo(tmp_path)

    payload = run_context(repo, home, "doctor")

    assert payload["ok"] is True
    db_path = Path(payload["database"])
    with sqlite3.connect(db_path) as con:
        indexes = {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {
        "idx_sources_context_path",
        "idx_sources_context_freshness",
        "idx_sources_context_priority_status",
        "idx_sources_scope_lookup",
        "idx_chunks_context_line_lookup",
        "idx_vectors_context_profile",
        "idx_vectors_profile_modality",
        "idx_usage_context_used",
        "idx_worker_runs_context_status",
    }.issubset(indexes)


def test_inventory_excludes_secret_and_noise_paths_by_default(tmp_path: Path) -> None:
    repo, home = make_repo(tmp_path)

    default_inventory = run_context(repo, home, "inventory")
    paths = {item["path"] for item in default_inventory["files"]}
    assert "README.md" in paths
    assert "src/app.py" in paths
    assert ".env" not in paths
    assert "node_modules/noise.js" not in paths

    with_excludes = run_context(repo, home, "inventory", "--show-excludes")
    excluded = {item["path"] for item in with_excludes["files"] if item["status"] == "excluded"}
    assert ".env" in excluded
    assert "node_modules/noise.js" in excluded


def test_ingest_search_lookup_freshness_and_rebuild(tmp_path: Path) -> None:
    repo, home = make_repo(tmp_path)

    pre = run_context(repo, home, "agent-preflight")
    assert pre["vector_available"] is False
    assert pre["worklist"]["extract"] >= 2
    assert "README.md" in pre["recommended_action"] or pre["worklist"]["extract"] >= 1

    ingest = run_context(repo, home, "ingest")
    assert ingest["summary"]["sources"] >= 2
    assert ingest["summary"]["vectors"] >= 2

    stats = run_context(repo, home, "stats")
    assert stats["counts"]["sources"] >= 2
    assert stats["counts"]["vectors"] >= 2
    assert stats["fts"]["chunk_fts"] is True

    search = run_context(repo, home, "search", "vector workflow", "--top-k", "3")
    assert search["ok"] is True
    assert 1 <= len(search["results"]) <= 3
    top = search["results"][0]
    assert {
        "path",
        "line_start",
        "line_end",
        "score",
        "vector_score",
        "lexical_score",
        "chunk_id",
        "stale",
        "indexed_at",
        "source_mtime",
        "git_commit",
    }.issubset(top)

    lookup = run_context(repo, home, "lookup", "--chunk-id", top["chunk_id"])
    assert lookup["chunk"]["line_start"] >= 1
    assert lookup["chunk"]["line_end"] >= lookup["chunk"]["line_start"]

    used = run_context(repo, home, "memory", "mark-used", "--chunk-id", top["chunk_id"], "--reason", "selected_context")
    assert used["ok"] is True
    stats = run_context(repo, home, "memory", "stats")
    assert stats["total_usage_events"] == 1
    promote = run_context(repo, home, "memory", "promote-plan")
    assert promote["ok"] is True
    assert promote["apply_supported"] is False

    mcp = run_context(repo, home, "mcp", "config")
    assert mcp["ok"] is True
    assert "context_mcp_server.py" in " ".join(mcp["server"]["args"])

    multi = run_context(repo, home, "freshness", "--scope", "repo,framework")
    assert multi["ok"] is True
    assert [ctx["scope"] for ctx in multi["contexts"]] == ["repo", "framework"]

    vector_plan = run_context(repo, home, "vector-rebuild", "plan")
    assert vector_plan["would_rebuild"]["chunks_to_revector"] >= 2
    vector_apply = run_context(repo, home, "vector-rebuild", "apply", "--plan", vector_plan["plan_id"])
    assert vector_apply["rebuilt_vectors"] >= 2

    (repo / "README.md").write_text(
        "# Localsetup Demo\n\nInstall workflow context changed after ingest.\n",
        encoding="utf-8",
    )
    stale = run_context(repo, home, "stale-files")
    assert "README.md" in stale["read_direct_paths"]

    plan = run_context(repo, home, "rebuild", "plan")
    assert plan["would_delete"]["sources"] >= 2
    rebuilt = run_context(repo, home, "rebuild", "apply", "--plan", plan["plan_id"])
    assert rebuilt["ok"] is True
    assert rebuilt["ingest"]["summary"]["sources"] >= 2

    (repo / "src" / "app.py").unlink()
    tombstone = run_context(repo, home, "ingest", "--changed-only")
    assert tombstone["summary"]["tombstoned"] >= 1
    prune_plan = run_context(repo, home, "prune", "plan")
    assert prune_plan["would_delete"]["deleted_sources"] >= 1
    prune_apply = run_context(repo, home, "prune", "apply", "--plan", prune_plan["plan_id"])
    assert prune_apply["summary"]["deleted_sources"] >= 1


def test_cli_delegates_context_index(tmp_path: Path) -> None:
    repo, home = make_repo(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(LOCALSETUP),
            "--repo",
            str(REPO_ROOT),
            "--home",
            str(home),
            "--target-directory",
            str(repo),
            "context-index",
            "doctor",
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr + completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["ok"] is True
    assert payload["context"]["scope_slug"] == "repo"

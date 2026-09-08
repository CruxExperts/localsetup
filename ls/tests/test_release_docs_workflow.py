"""Release documents gate the actual workflow and bind draft publication."""
from pathlib import Path

import pytest
import yaml

from ls.core.release_docs import github


ROOT = Path(__file__).resolve().parents[2]


def test_prepare_precedes_exact_commit_build_and_repair_skips_build():
    workflow = yaml.safe_load((ROOT / ".github/workflows/publish.yml").read_text())
    prepare = workflow["jobs"]["prepare-documentation"]
    publish = workflow["jobs"]["publish"]
    assert publish["needs"] == "prepare-documentation"
    assert "inputs.mode != 'repair'" in publish["if"]
    assert "inputs.mode != 'qualify'" in publish["if"]
    checkout = next(step for step in publish["steps"] if step["name"] == "Checkout")
    assert checkout["with"]["ref"] == "${{ needs.prepare-documentation.outputs.head }}"
    names = [step["name"] for step in publish["steps"]]
    assert names.index("Check release documentation before building") < names.index("Build public artifact")
    proposed = next(step for step in prepare["steps"] if step["name"].startswith("Audit,"))
    integrated = next(step for step in prepare["steps"] if step["name"] == "Integrate verified documentation")
    assert "QC_LLM_API_KEY" in proposed["env"]
    assert "QC_LLM_API_KEY" not in integrated["env"]
    assert "if" not in integrated
    assert 'if [[ "$RELEASE_DOCS_MODE" != qualify ]]; then flags+=(--push); fi' in integrated["run"]


def test_draft_check_rejects_notes_and_asset_drift(monkeypatch, tmp_path):
    record = {"version": "1.2.3"}
    from ls.core.release_docs import render
    monkeypatch.setattr(render, "notes", lambda value: "accepted notes\n")
    monkeypatch.setattr(github, "git", lambda root, *args:
                        "a" * 40 + "\trefs/tags/v1.2.3" if args[0] == "ls-remote" else "a" * 40)
    release = {"tagName": "v1.2.3", "targetCommitish": "a" * 40,
               "isDraft": True, "body": "accepted notes", "assets": [
                   {"name": "localsetup-v1.2.3.tar.gz" + suffix}
                   for suffix in ("", ".sha256", ".cdx.json")]}
    monkeypatch.setattr(github, "gh_json", lambda *args: release)
    assert github.check_draft(tmp_path, "v1.2.3", record, "a" * 40)["ok"]
    release["body"] = "changed after review"
    with pytest.raises(ValueError, match="notes differ"):
        github.check_draft(tmp_path, "v1.2.3", record, "a" * 40)
    release["body"] = "accepted notes"
    release["assets"].pop()
    with pytest.raises(ValueError, match="missing documented"):
        github.check_draft(tmp_path, "v1.2.3", record, "a" * 40)
    with pytest.raises(ValueError, match="checked commit"):
        github.check_draft(tmp_path, "v1.2.3", record, "b" * 40)
    release["tagName"] = "v1.2.2"
    with pytest.raises(ValueError, match="Remote draft tag"):
        github.check_draft(tmp_path, "v1.2.3", record, "a" * 40)


def test_repair_rejects_unreleased_executable_work(monkeypatch, tmp_path):
    baseline = {"commit": "a" * 40}
    monkeypatch.setattr(github, "git", lambda *args: "README.md\nls/core/new_feature.py")
    with pytest.raises(ValueError, match="unreleased non-documentation"):
        github.guard_repair(tmp_path, baseline, "b" * 40)
    monkeypatch.setattr(github, "git", lambda *args: "README.md\nls/docs/releases/1.2.3.json")
    github.guard_repair(tmp_path, baseline, "b" * 40)

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tools.qc_patrol.chunking import chunk_text
from tools.qc_patrol.cli import main as qc_main
from tools.qc_patrol.config import load_config
from tools.qc_patrol.diff_reader import read_diff
from tools.qc_patrol.deterministic_checks import QC_WORKFLOWS, check_release_exclusions, scan_workflow_permissions
from tools.qc_patrol.docs_drift import docs_alignment_findings
from tools.qc_patrol.issue_writer import extract_handoff, find_duplicate, fingerprint_for, issue_body
from tools.qc_patrol.llm_client import LLMClient, LLMDisabled
from tools.qc_patrol.pr_writer import plan_autofix
from tools.qc_patrol.redaction import redact_text
from tools.qc_patrol.review_contracts import parse_strict_json


REPO = Path(__file__).resolve().parents[2]


def test_qc_config_loads_defaults_and_blank_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QC_LLM_MAX_TOKENS", "")
    config = load_config(REPO)
    assert "qc-patrol" in config.labels
    assert config.llm.max_tokens == 2000
    assert config.llm.api_style == "chat_completions"


def test_redaction_removes_secret_shapes() -> None:
    text = """API_TOKEN=ghp_abcdefghijklmnopqrstuvwxyz123456
password: supersecret
https://user:token@example.com/path
-----BEGIN PRIVATE KEY-----
abc
-----END PRIVATE KEY-----
"""
    redacted = redact_text(text)
    assert "ghp_" not in redacted
    assert "supersecret" not in redacted
    assert "user:token" not in redacted
    assert "example.com" not in redacted
    assert "PRIVATE KEY-----\nabc" not in redacted


def test_chunk_text_respects_byte_boundaries() -> None:
    chunks = chunk_text("sample", "aé" * 10, 5)
    assert len(chunks) > 1
    assert all(int(chunk["bytes"]) <= 5 for chunk in chunks)
    assert "".join(str(chunk["text"]) for chunk in chunks) == "aé" * 10


def test_strict_json_schema_failure_writes_raw(tmp_path: Path) -> None:
    raw = tmp_path / "raw.json"
    with pytest.raises(ValueError, match="schema"):
        parse_strict_json('{"findings":[{"category":"bad"}]}', raw)
    payload = json.loads(raw.read_text(encoding="utf-8"))
    assert payload["schema_errors"]


def _finding(title: str = "Example finding") -> dict[str, object]:
    return {
        "category": "workflow_security",
        "severity": "high",
        "title": title,
        "body": "Body",
        "affected_paths": [".github/workflows/example.yml"],
        "region": "permissions",
        "check_type": "deterministic",
    }


def test_fingerprint_stability_and_duplicate_matching() -> None:
    finding = _finding("  Example   Finding ")
    same = _finding("example finding")
    assert fingerprint_for(finding) == fingerprint_for(same)
    body = issue_body(finding)
    handoff = extract_handoff(body)
    assert handoff is not None
    duplicate = find_duplicate([{"number": 7, "body": body}], same)
    assert duplicate and duplicate["number"] == 7


def test_workflow_permission_scan_accepts_qc_workflows() -> None:
    findings = scan_workflow_permissions(REPO)
    high_titles = {finding["title"] for finding in findings if finding["severity"] in {"high", "critical"}}
    assert not high_titles


def test_qc_workflows_are_exact_private_paths() -> None:
    data = yaml.safe_load((REPO / "_localsetup/config/pack.yaml").read_text(encoding="utf-8"))
    private = set(data["public_private"]["private_paths"])
    assert QC_WORKFLOWS <= private
    assert check_release_exclusions(REPO) == []


def test_release_artifact_exclusion_detects_qc_workflow_in_tar(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.tar.gz"
    with tarfile.open(artifact, "w:gz") as tar:
        member = tarfile.TarInfo(".github/workflows/qc-ci.yml")
        data = b"name: qc-ci\n"
        member.size = len(data)
        tar.addfile(member, fileobj=io.BytesIO(data))
    findings = check_release_exclusions(REPO, artifact)
    assert any("included in release artifact" in finding["title"] for finding in findings)


def test_new_qc_workflow_static_contracts() -> None:
    for workflow in sorted((REPO / ".github/workflows").glob("qc-*.yml")):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        assert "permissions" in data, workflow
        text = workflow.read_text(encoding="utf-8")
        assert "actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd" in text
        if workflow.name == "qc-pr-review.yml":
            assert "github.event.pull_request.head.repo.full_name == github.repository" in text
            assert "repository: ${{ github.event.pull_request.head.repo.full_name || github.repository }}" in text
            assert "QC_BASE_REMOTE: https://github.com/${{ github.repository }}.git" in text
            assert "github.event.pull_request.base.sha" not in "\n".join(
                str(step.get("run", "")) for step in data["jobs"]["pr-review"]["steps"] if isinstance(step, dict)
            )
            assert "pull_request_target" not in text
        if workflow.name == "qc-autofix.yml":
            assert set(data[True].keys()) == {"workflow_dispatch"}
            assert "github.event.inputs.issue" not in "\n".join(
                str(step.get("run", "")) for step in data["jobs"]["autofix"]["steps"] if isinstance(step, dict)
            )


def test_llm_client_disabled_without_secret() -> None:
    config = load_config(REPO).llm
    with pytest.raises(LLMDisabled):
        LLMClient(config).complete("prompt")


def test_llm_client_success_and_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    config = load_config(REPO).llm
    config = SimpleNamespace(**{**config.__dict__, "base_url": "https://example.test", "api_key": "secret", "retry_count": 1})
    calls = {"count": 0}

    class Response:
        content = b"{}"

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": '{"findings":[]}'}}]}

    def post(*args: object, **kwargs: object) -> Response:
        calls["count"] += 1
        if calls["count"] == 1:
            raise TimeoutError("timeout")
        return Response()

    monkeypatch.setattr("tools.qc_patrol.llm_client.requests.post", post)
    monkeypatch.setattr("tools.qc_patrol.llm_client.time.sleep", lambda _seconds: None)
    assert LLMClient(config).complete("api_key=secret-value") == '{"findings":[]}'
    assert calls["count"] == 2


def test_llm_strict_json_invalid_response(tmp_path: Path) -> None:
    raw = tmp_path / "raw.json"
    with pytest.raises(ValueError, match="valid JSON"):
        parse_strict_json("not json", raw)
    assert "not json" in raw.read_text(encoding="utf-8")


def test_read_diff_uses_hunks(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "@@ -1 +1 @@\n-old\n+new\n"

    def run(command: list[str], **kwargs: object) -> Result:
        calls.append(command)
        return Result()

    monkeypatch.setattr("tools.qc_patrol.diff_reader.subprocess.run", run)
    assert "+new" in read_diff(REPO, "base", "head")
    assert "--stat" not in calls[0]
    assert "--unified=80" in calls[0]


def test_autofix_only_allows_explicit_ids(tmp_path: Path) -> None:
    assert plan_autofix("123", dry_run=False, create_pr=True, out=tmp_path)["create_pr"] is False
    assert plan_autofix("generated-docs-refresh", dry_run=False, create_pr=True, out=tmp_path)["create_pr"] is True


def test_llm_error_artifact_redacts_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def complete(_self: object, _prompt: str) -> str:
        raise RuntimeError("failed calling https://llm.example.test/chat/completions")

    monkeypatch.setattr("tools.qc_patrol.cli.LLMClient.complete", complete)
    monkeypatch.setenv("QC_LLM_BASE_URL", "https://llm.example.test")
    monkeypatch.setenv("QC_LLM_API_KEY", "secret")
    result = qc_main(
        [
            "pr-review",
            "--subject-repo",
            str(REPO),
            "--base",
            "HEAD",
            "--head",
            "HEAD",
            "--out",
            str(tmp_path),
            "--llm-mode",
            "auto",
        ]
    )
    assert result == 0
    payload = json.loads((tmp_path / "llm-error.json").read_text(encoding="utf-8"))
    assert "llm.example.test" not in payload["error"]
    assert payload["endpoint_alias"]


def test_docs_alignment_failure_becomes_handoff(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 1
        stdout = '{"ok": false, "findings": [{"id": "drift"}]}'
        stderr = ""

    monkeypatch.setattr("tools.qc_patrol.docs_drift.subprocess.run", lambda *args, **kwargs: Result())
    findings = docs_alignment_findings(REPO)
    assert findings[0]["category"] == "docs"
    assert findings[0]["check_type"] == "docs_alignment"

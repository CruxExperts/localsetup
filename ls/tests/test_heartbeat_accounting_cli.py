import json
from pathlib import Path
import subprocess
import sys

from ls.core.agent import heartbeat_budget_store as store
from ls.tests.test_heartbeat_budget_store import document
from ls.tests.test_heartbeat_budget import reserve

ROOT = Path(__file__).resolve().parents[2]


def call(workspace, *args, expected=0):
    result = subprocess.run([sys.executable, str(ROOT/"ls/tools/localsetup.py"),
        "--source-root", str(ROOT), "--target-directory", str(workspace),
        "harness", "codex-heartbeat", *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, timeout=15)
    assert result.returncode == expected, result.stderr
    return json.loads(result.stdout) if expected == 0 else result


def private(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)
    return path


def test_public_plan_apply_inspect_review_and_budget(tmp_path):
    workspace, root = tmp_path/"workspace", tmp_path/"control"
    workspace.mkdir()
    source = private(tmp_path/"policy-input.json", document(workspace))
    plan = call(workspace, "accounting", "init", "--plan", "--input", source, "--accounting-root", root)
    assert not root.exists()
    state = call(workspace, "accounting", "init", "--apply", "--input", source,
                 "--accounting-root", root, "--policy-sha256", plan["sha256"])
    state = store.append(root, workspace, reserve(), state["head"], binding="e"*64)
    state = store.append(root, workspace, dict(type="result", operation="one", result="c"*64), state["head"])
    review = private(tmp_path/"review.json", dict(operation="one", result="c"*64,
        decision="no_progress", evidence="d"*64, rationale="Controller checked criterion"))
    reviewed = call(workspace, "accounting", "review", "--accounting-root", root,
                    "--input", review, "--expected-head", state["head"])
    assert reviewed["summary"]["consecutive_no_progress"] == 1
    inspected = call(workspace, "accounting", "inspect", "--accounting-root", root)
    assert inspected["head"] == reviewed["head"]
    report = call(workspace, "budget", "--accounting-root", root)
    assert report["execution_accounting"]["summary"]["charged"]["tokens"] == 100
    assert report["execution_accounting"]["financial_estimate"]["status"] == "unavailable"
    call(workspace, "accounting", "review", "--accounting-root", root,
         "--input", review, "--expected-head", state["head"], expected=2)


def test_missing_state_and_bad_apply_never_create(tmp_path):
    workspace, root = tmp_path/"workspace", tmp_path/"absent"
    workspace.mkdir()
    call(workspace, "accounting", "inspect", "--accounting-root", root, expected=2)
    source = private(tmp_path/"policy.json", document(workspace))
    call(workspace, "accounting", "init", "--apply", "--input", source,
         "--accounting-root", root, expected=2)
    assert not root.exists()
    source.chmod(0o644)
    call(workspace, "accounting", "init", "--plan", "--input", source,
         "--accounting-root", root, expected=2)


def test_workspace_authored_review_input_is_refused(tmp_path):
    workspace = tmp_path/"workspace"
    workspace.mkdir()
    source = private(workspace/"model-review.json", {"decision": "accepted"})
    result = call(workspace, "accounting", "review", "--accounting-root", tmp_path/"control",
                  "--input", source, "--expected-head", "a"*64, expected=2)
    assert "accepted" not in result.stderr
    assert not (tmp_path/"control").exists()

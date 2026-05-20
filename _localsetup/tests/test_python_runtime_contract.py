from pathlib import Path
import re
import tomllib

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_python_runtime_contract_is_312() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    install = (ROOT / "install").read_text(encoding="utf-8")
    tooling_policy = (ROOT / "_localsetup" / "docs" / "TOOLING_POLICY.md").read_text(encoding="utf-8")
    validator = (ROOT / "_localsetup" / "tools" / "validate_output_contract.py").read_text(encoding="utf-8")

    assert pyproject["project"]["requires-python"] == ">=3.12"
    assert lock["requires-python"] == ">=3.12"
    assert (ROOT / ".python-version").read_text(encoding="utf-8").strip() == "3.12"
    assert 'MIN_PYTHON_VERSION="3.12.0"' in install
    assert "python3 >= 3.12 is required" in install
    assert "Minimum supported version: Python 3.12." in tooling_policy
    assert "Minimum supported version: Python 3.12." in validator
    dependencies = pyproject["project"]["dependencies"]
    assert not any(dependency.startswith("tomli") for dependency in dependencies)
    assert "PGPy>=0.6.0" in dependencies
    assert "tomli" not in tooling_policy


def test_ci_uses_python_312_as_supported_runtime() -> None:
    workflow_paths = [
        ROOT / ".github" / "workflows" / "pr-validation.yml",
        ROOT / ".github" / "workflows" / "docs-sync.yml",
    ]
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in workflow_paths
    }

    matrix_versions = workflows["pr-validation.yml"]["jobs"]["framework-validation"]["strategy"]["matrix"][
        "python-version"
    ]
    assert matrix_versions == ["3.12"]

    docs_steps = workflows["docs-sync.yml"]["jobs"]["verify-generated-docs"]["steps"]
    docs_python_versions = [
        step["with"]["python-version"]
        for step in docs_steps
        if step.get("uses", "").startswith("actions/setup-python")
    ]
    assert docs_python_versions == ["3.12"]

    all_workflow_text = "\n".join(path.read_text(encoding="utf-8") for path in workflow_paths)
    assert not re.search(r'python-version:\s*["\']?3\.10\b', all_workflow_text)
    assert 'python-version: "3.x"' not in all_workflow_text

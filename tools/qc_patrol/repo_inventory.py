from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

import yaml

from _localsetup.tools.docs_alignment import collect_inventory as collect_docs_inventory
from _localsetup.tools.docs_alignment import collect_truth_map

from .schemas import INVENTORY_SCHEMA, validate_payload


PACKAGE_FILES = {
    "pyproject.toml": "python_project",
    "uv.lock": "uv_lock",
    "VERSION": "version",
    "package.json": "node_package",
    "package-lock.json": "node_lock",
    "pnpm-lock.yaml": "pnpm_lock",
    "yarn.lock": "yarn_lock",
}


def _git(repo: Path, args: list[str]) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def _git_files(repo: Path) -> list[str]:
    return sorted(line for line in _git(repo, ["ls-files"]).splitlines() if line)


def _head_sha(repo: Path) -> str:
    try:
        return _git(repo, ["rev-parse", "HEAD"])
    except subprocess.CalledProcessError:
        return ""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _frontmatter_version(path: Path) -> str:
    text = _read_text(path)
    if not text.startswith("---\n"):
        return ""
    end = text.find("\n---\n", 4)
    if end == -1:
        return ""
    data = yaml.safe_load(text[4:end]) or {}
    return str(data.get("version", "")) if isinstance(data, dict) else ""


def _workflow_trigger_names(data: dict[str, Any]) -> list[str]:
    triggers = data.get("on", data.get(True, {}))
    if isinstance(triggers, str):
        return [triggers]
    if isinstance(triggers, list):
        return sorted(str(item) for item in triggers)
    if isinstance(triggers, dict):
        return sorted(str(key) for key in triggers)
    return []


def _workflow_name(path: Path) -> str:
    data = yaml.safe_load(_read_text(path)) or {}
    return str(data.get("name", path.stem)) if isinstance(data, dict) else path.stem


def _workflow_surface(repo: Path, path: str) -> dict[str, Any]:
    full = repo / path
    data = yaml.safe_load(_read_text(full)) or {}
    if not isinstance(data, dict):
        data = {}
    return {
        "path": path,
        "name": str(data.get("name", Path(path).stem)),
        "triggers": _workflow_trigger_names(data),
        "permissions_present": "permissions" in data,
        "known_category": "qc" if Path(path).name.startswith("qc-") else "repository",
        "hash": _sha256(full),
    }


def _package_version(repo: Path, path: str, kind: str) -> str:
    full = repo / path
    if path == "VERSION":
        return _read_text(full).strip()
    if path == "pyproject.toml":
        match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', _read_text(full))
        return match.group(1) if match else ""
    if path == "package.json":
        try:
            data = json.loads(_read_text(full))
        except json.JSONDecodeError:
            return ""
        return str(data.get("version", "")) if isinstance(data, dict) else ""
    return "" if kind.endswith("_lock") else ""


def _private_paths(repo: Path, files: set[str]) -> list[dict[str, Any]]:
    path = repo / "_localsetup/config/pack.yaml"
    if not path.exists():
        return []
    data = yaml.safe_load(_read_text(path)) or {}
    configured = ((data.get("public_private") or {}).get("private_paths") or []) if isinstance(data, dict) else []
    rows = []
    for pattern in sorted(str(item) for item in configured):
        matched = [file for file in files if file == pattern or file.startswith(pattern.rstrip("/") + "/")]
        rows.append({"path": pattern, "tracked": bool(matched), "matched_count": len(matched)})
    return rows


def _generated_artifacts(repo: Path, files: set[str]) -> list[dict[str, Any]]:
    artifacts = []
    for path in sorted(files):
        if not path.startswith("_localsetup/docs/_generated/"):
            continue
        artifacts.append(
            {
                "path": path,
                "emitter": "docs-align" if path.endswith((".json", ".md")) else "unknown",
                "source_inputs": ["live repository manifests"],
                "registered": path in files,
                "hash": _sha256(repo / path),
            }
        )
    return artifacts


def _version_references(repo: Path, docs: list[dict[str, Any]], truth_version: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    version_re = re.compile(r"\bv?\d+\.\d+\.\d+(?:[-+][A-Za-z0-9_.-]+)?\b")
    for doc in docs:
        path = str(doc["path"])
        full = repo / path
        if not full.exists():
            continue
        for line_no, line in enumerate(_read_text(full).splitlines(), start=1):
            for match in version_re.finditer(line):
                references.append(
                    {
                        "path": path,
                        "line": line_no,
                        "value": match.group(0).lstrip("v"),
                        "matches_truth": match.group(0).lstrip("v") == truth_version,
                        "doc_class": doc.get("class", ""),
                    }
                )
    return references


def build_inventory(repo: Path) -> dict[str, Any]:
    repo = repo.resolve()
    files = _git_files(repo)
    file_set = set(files)
    docs_inventory = collect_docs_inventory(repo)
    truth_map = collect_truth_map(repo)
    version_truth = truth_map.get("truths", {}).get("version", {})
    truth_version = str(version_truth.get("value", ""))
    docs = [
        {
            "path": row["path"],
            "class": row["class"],
            "status": row.get("status", ""),
            "frontmatter_version": row.get("version", ""),
            "hash": _sha256(repo / row["path"]),
            "generated": row["class"] == "generated",
            "owner": row.get("owner_skill") or row.get("owner_package") or "",
        }
        for row in docs_inventory.get("docs", [])
        if (repo / row["path"]).exists()
    ]
    packages = [
        {
            "path": path,
            "kind": PACKAGE_FILES[path],
            "version": _package_version(repo, path, PACKAGE_FILES[path]),
            "hash": _sha256(repo / path),
        }
        for path in sorted(file_set & set(PACKAGE_FILES))
    ]
    workflow_packages = [
        {
            "package": row.get("package", ""),
            "workflow_id": row.get("workflow_id", ""),
            "path": row.get("path", ""),
            "packs": row.get("packs", []),
        }
        for row in docs_inventory.get("workflows", [])
    ]
    payload = {
        "schema_version": "qc.inventory.v2",
        "created_at_unix": int(time.time()),
        "head_sha": _head_sha(repo),
        "tracked_file_count": len(files),
        "files": [{"path": path, "hash": _sha256(repo / path)} for path in files if (repo / path).is_file()],
        "surfaces": {
            "docs": docs,
            "workflows": [_workflow_surface(repo, path) for path in files if path.startswith(".github/workflows/") and path.endswith((".yml", ".yaml"))],
            "generated_artifacts": _generated_artifacts(repo, file_set),
            "packages": packages,
            "skills": docs_inventory.get("skills", []),
            "workflow_packages": workflow_packages,
            "private_paths": _private_paths(repo, file_set),
            "registry_catalog_metadata": {
                "pack_config": "_localsetup/config/pack.yaml" in file_set,
                "generated_facts": "_localsetup/docs/_generated/facts.json" in file_set,
                "generated_skill_taxonomy": "_localsetup/docs/_generated/skill-taxonomy.json" in file_set,
                "ci_workflows": docs_inventory.get("ci_workflows", []),
            },
            "version_references": _version_references(repo, docs, truth_version),
        },
        "version_truth": version_truth,
    }
    errors = validate_payload(payload, INVENTORY_SCHEMA)
    if errors:
        raise ValueError("invalid QC inventory: " + "; ".join(errors))
    return payload

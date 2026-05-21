from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_CONFIG_PATH = Path(".ai/qc/config.example.yml")


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    retry_count: int
    api_style: str
    endpoint_alias: str
    organization: str
    project: str


@dataclass(frozen=True)
class QCConfig:
    labels: list[str]
    severity_labels: dict[str, str]
    category_labels: dict[str, str]
    max_chunk_bytes: int
    llm: LLMConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"QC config must be a mapping: {path}")
    return data


def _env_value(name: str, data: dict[str, Any], key: str, default: Any = "") -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        value = data.get(key, default)
    return str(value)


def load_config(repo: Path, config_path: Path | None = None) -> QCConfig:
    path = config_path or repo / DEFAULT_CONFIG_PATH
    data = _read_yaml(path)
    labels = data.get("labels", ["qc-patrol", "ai-generated", "needs-planning-review"])
    if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
        raise ValueError("QC labels must be a list of strings")
    llm_data = data.get("llm", {})
    if not isinstance(llm_data, dict):
        raise ValueError("QC llm config must be a mapping")
    llm = LLMConfig(
        base_url=os.environ.get("QC_LLM_BASE_URL", str(llm_data.get("base_url", ""))),
        api_key=os.environ.get("QC_LLM_API_KEY", ""),
        model=_env_value("QC_LLM_MODEL", llm_data, "model", "gpt-4.1-mini"),
        temperature=float(_env_value("QC_LLM_TEMPERATURE", llm_data, "temperature", 0)),
        max_tokens=int(_env_value("QC_LLM_MAX_TOKENS", llm_data, "max_tokens", 2000)),
        timeout_seconds=float(_env_value("QC_LLM_TIMEOUT_SECONDS", llm_data, "timeout_seconds", 30)),
        retry_count=int(_env_value("QC_LLM_RETRY_COUNT", llm_data, "retry_count", 1)),
        api_style=_env_value("QC_LLM_API_STYLE", llm_data, "api_style", "chat_completions"),
        endpoint_alias=_env_value("QC_LLM_ENDPOINT_ALIAS", llm_data, "endpoint_alias", "configured-qc-llm"),
        organization=os.environ.get("QC_LLM_ORGANIZATION", str(llm_data.get("organization", ""))),
        project=os.environ.get("QC_LLM_PROJECT", str(llm_data.get("project", ""))),
    )
    return QCConfig(
        labels=labels,
        severity_labels={str(k): str(v) for k, v in (data.get("severity_labels") or {}).items()},
        category_labels={str(k): str(v) for k, v in (data.get("category_labels") or {}).items()},
        max_chunk_bytes=int(data.get("max_chunk_bytes", 24000)),
        llm=llm,
    )

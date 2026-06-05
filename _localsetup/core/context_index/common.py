"""Localsetup context index: SQLite-backed freshness, ingest, and vector search."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    import yaml
except Exception:  # pragma: no cover - surfaced by config commands.
    yaml = None  # type: ignore[assignment]


SCHEMA_VERSION = "1.0"
CHUNKER_VERSION = "1.0"
EXTRACTOR_VERSION = "1.0"
DEFAULT_VECTOR_DIMENSIONS = 64
GLOBAL_DB_REL = ".local/share/localsetup/context-index/context-index.sqlite3"
REPO_DB_REL = ".localsetup/context-index/context-index.sqlite3"
REPO_CONFIG_REL = ".localsetup/context-index/config.yaml"
GLOBAL_CONFIG_REL = ".config/localsetup/context-index/config.yaml"
LOG_REL = ".localsetup/context-index/logs/context-index.jsonl"
UUID7_RANDOM_BITS = 74


class ContextIndexError(RuntimeError):
    def __init__(self, code: str, message: str, recommended_action: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recommended_action = recommended_action


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def iso_from_ns(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value / 1_000_000_000, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8", errors="replace"))


def stable_json_hash(payload: Any) -> str:
    return sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def uuid7() -> str:
    """Return an RFC 9562-style UUIDv7 string for Python 3.12+."""
    unix_ms = int(time.time() * 1000) & ((1 << 48) - 1)
    rand = random.SystemRandom().getrandbits(UUID7_RANDOM_BITS)
    value = unix_ms << 80
    value |= 0x7 << 76
    value |= ((rand >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= rand & ((1 << 62) - 1)
    hexed = f"{value:032x}"
    return f"{hexed[0:8]}-{hexed[8:12]}-{hexed[12:16]}-{hexed[16:20]}-{hexed[20:32]}"


def slugify(value: str) -> str:
    cleaned = []
    for char in value.lower():
        cleaned.append(char if char.isalnum() else "-")
    slug = "".join(cleaned).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug or "default"


def json_print(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def error_payload(command: str, exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ContextIndexError):
        return {
            "ok": False,
            "command": command,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "recommended_action": exc.recommended_action,
            },
        }
    return {
        "ok": False,
        "command": command,
        "error": {
            "code": type(exc).__name__,
            "message": str(exc),
            "recommended_action": "Inspect the command arguments and context-index configuration.",
        },
    }


def default_config(repo_root: Path, home: Path) -> dict[str, Any]:
    repo_slug = slugify(repo_root.name)
    return {
        "context_index": {
            "enabled": True,
            "identity": {
                "tenant_slug": "local",
                "namespace_slug": "repos",
                "corpus_slug": repo_slug,
            },
            "storage": {
                "mode": "repo_plus_global",
                "repo_database": {"enabled": True, "path": REPO_DB_REL},
                "global_database": {"enabled": True, "path": str(home / GLOBAL_DB_REL)},
                "sqlite": {"busy_timeout_ms": 5000, "journal_mode": "WAL", "synchronous": "NORMAL"},
            },
            "scopes": {
                "default_query": ["repo", "framework"],
                "definitions": {
                    "repo": {
                        "type": "repo",
                        "roots": ["."],
                        "include": ["**/*"],
                        "exclude": DEFAULT_EXCLUDES,
                        "max_file_bytes": 1048576,
                    },
                    "framework": {
                        "type": "framework",
                        "roots": ["_localsetup"],
                        "include": [
                            "_localsetup/docs/**/*.md",
                            "_localsetup/docs/_generated/*.json",
                            "_localsetup/skills/**/SKILL.md",
                            "_localsetup/workflows/**",
                        ],
                        "exclude": DEFAULT_EXCLUDES,
                        "max_file_bytes": 1048576,
                    },
                },
            },
            "freshness": {
                "default_mode": "quick",
                "hash_when_quick_fields_change": True,
                "deep_hash_all_files": False,
                "git_blob_check": True,
                "fail_closed_on_unknown": True,
            },
            "chunking": {"target_lines": 80, "overlap_lines": 8, "max_chunks_per_file": 500},
            "embeddings": {
                "enabled": True,
                "provider": "local_hash",
                "model": "localsetup-hash-v1",
                "dimensions": DEFAULT_VECTOR_DIMENSIONS,
                "document_prefix": "",
                "query_prefix": "",
                "endpoint": "",
                "api_key_env": "",
                "timeout_seconds": 30,
            },
            "retrieval": {
                "default_top_k": 10,
                "max_top_k": 50,
                "hybrid": {"lexical_weight": 0.35, "vector_weight": 0.65},
            },
            "worker": {
                "max_runtime_seconds": 300,
                "batch_file_limit": 50,
                "batch_vector_limit": 250,
            },
            "logging": {
                "enabled": True,
                "level": "info",
                "max_bytes": 10485760,
                "max_files": 5,
            },
        }
    }


DEFAULT_EXCLUDES = [
    ".git/**",
    ".localsetup/**",
    ".venv/**",
    "_localsetup/.cache/**",
    "_localsetup/docs/local-context/**",
    "_localsetup/logs/**",
    "venv/**",
    "node_modules/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".cache/**",
    ".codex/runs/**",
    ".git-state-snapshots/**",
    ".localsetup-maint/**",
    "dist/**",
    "build/**",
    "coverage/**",
    "logs/**",
    "state/**",
    "scrapling_output/**",
    "localsetup.egg-info/**",
    "*.pyc",
    "*.log",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.kdbx",
    "**/*secret*",
    "**/*credential*",
    "**/*token*",
]


HIGH_PRIORITY_PATTERNS = [
    "README*",
    "AGENTS.md",
    ".agentlens/**/*.md",
    "_localsetup/docs/**/*.md",
    "_localsetup/docs/_generated/*.json",
    "_localsetup/skills/**/SKILL.md",
    "_localsetup/workflows/**",
]


@dataclass(frozen=True)
class Runtime:
    repo_root: Path
    home: Path
    config: dict[str, Any]
    context: dict[str, str]
    db_path: Path
    scope: str

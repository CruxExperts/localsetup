"""Localsetup context index: SQLite-backed freshness, ingest, and vector search."""

from __future__ import annotations

import argparse
import fnmatch
import re
import sqlite3
from pathlib import Path
from typing import Any

import requests

from .identity import iso_from_ns, sha256_bytes, sha256_text, slugify, stable_json_hash, utc_now, uuid7
from .models import ContextIndexError, Runtime
from .reporting import error_payload, json_print

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
                        "roots": ["ls"],
                        "include": [
                            "ls/docs/**/*.md",
                            "ls/docs/_generated/*.json",
                            "ls/skills/**/SKILL.md",
                            "ls/workflows/**",
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
    "ls/.cache/**",
    "ls/docs/local-context/**",
    "ls/logs/**",
    "venv/**",
    "node_modules/**",
    "__pycache__/**",
    ".pytest_cache/**",
    ".cache/**",
    ".codex/runs/**",
    ".agents/state/**",
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
    "ls/docs/**/*.md",
    "ls/docs/_generated/*.json",
    "ls/skills/**/SKILL.md",
    "ls/workflows/**",
]

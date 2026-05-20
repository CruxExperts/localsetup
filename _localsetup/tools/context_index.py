#!/usr/bin/env python3
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
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def read_yaml(path: Path) -> dict[str, Any]:
    if yaml is None:
        raise ContextIndexError("MISSING_DEPENDENCY", "PyYAML is required for context-index config.")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ContextIndexError("INVALID_CONFIG", f"Config root must be a mapping: {path}")
    return data


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(repo_root: Path, home: Path) -> tuple[dict[str, Any], list[str]]:
    config = default_config(repo_root, home)
    loaded: list[str] = []
    global_path = home / GLOBAL_CONFIG_REL
    repo_path = repo_root / REPO_CONFIG_REL
    for path in (global_path, repo_path):
        if path.is_file():
            config = deep_merge(config, read_yaml(path))
            loaded.append(str(path))
    return config, loaded


def context_for(config: dict[str, Any], repo_root: Path, scope: str) -> dict[str, str]:
    ci = config["context_index"]
    ident = ci.get("identity", {})
    if scope == "framework":
        tenant, namespace, corpus = "local", "framework", "localsetup"
    elif scope == "global":
        raise ContextIndexError("UNSUPPORTED_SCOPE", "context-index global scope has been removed")
    else:
        tenant = str(ident.get("tenant_slug") or "local")
        namespace = str(ident.get("namespace_slug") or "repos")
        corpus = str(ident.get("corpus_slug") or slugify(repo_root.name))
    return {
        "tenant_slug": tenant,
        "namespace_slug": namespace,
        "corpus_slug": corpus,
        "scope_slug": scope,
        "context_key": f"{tenant}/{namespace}/{corpus}/{scope}",
    }


def db_path_for(config: dict[str, Any], repo_root: Path, home: Path, scope: str, database: str | None = None) -> Path:
    ci = config["context_index"]
    storage = ci.get("storage", {})
    if database == "global" or scope in {"framework", "global"} or storage.get("mode") in {"global", "central_sqlite"}:
        return Path(str(storage.get("global_database", {}).get("path") or home / GLOBAL_DB_REL)).expanduser()
    return (repo_root / str(storage.get("repo_database", {}).get("path") or REPO_DB_REL)).resolve()


def runtime(args: argparse.Namespace, scope: str | None = None, database: str | None = None) -> Runtime:
    target_root = Path(args.repo).expanduser().resolve()
    source_root = Path(getattr(args, "source_root", None) or target_root).expanduser().resolve()
    home = Path(args.home).expanduser().resolve()
    selected_scope = scope or getattr(args, "scope", "repo") or "repo"
    first_scope = str(selected_scope).split(",")[0].strip() or "repo"
    repo_root = source_root if first_scope == "framework" else target_root
    config, _ = load_config(repo_root, home)
    ctx = context_for(config, repo_root, first_scope)
    db_path = db_path_for(config, repo_root, home, first_scope, database=database)
    rt = Runtime(repo_root, home, config, ctx, db_path, first_scope)
    scope_definition(rt, first_scope)
    return rt


def parse_scopes(value: str | None) -> list[str]:
    scopes = [part.strip() for part in str(value or "repo").split(",") if part.strip()]
    return scopes or ["repo"]


def connect(rt: Runtime) -> sqlite3.Connection:
    rt.db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(rt.db_path)
    con.row_factory = sqlite3.Row
    sqlite_cfg = rt.config["context_index"].get("storage", {}).get("sqlite", {})
    con.execute(f"PRAGMA busy_timeout={int(sqlite_cfg.get('busy_timeout_ms', 5000))}")
    con.execute(f"PRAGMA journal_mode={str(sqlite_cfg.get('journal_mode', 'WAL'))}")
    con.execute(f"PRAGMA synchronous={str(sqlite_cfg.get('synchronous', 'NORMAL'))}")
    migrate(con)
    return con


def migrate(con: sqlite3.Connection) -> None:
    con.executescript(
        """
        DROP INDEX IF EXISTS idx_usage_chunk;
        DROP INDEX IF EXISTS idx_usage_context_used;
        DROP TABLE IF EXISTS usage_events;

        CREATE TABLE IF NOT EXISTS database_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS contexts (
          scope_id TEXT PRIMARY KEY,
          tenant_slug TEXT NOT NULL,
          namespace_slug TEXT NOT NULL,
          corpus_slug TEXT NOT NULL,
          scope_slug TEXT NOT NULL,
          context_key TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
          source_id TEXT PRIMARY KEY,
          scope_id TEXT NOT NULL,
          context_key TEXT NOT NULL,
          tenant_slug TEXT NOT NULL,
          namespace_slug TEXT NOT NULL,
          corpus_slug TEXT NOT NULL,
          scope_slug TEXT NOT NULL,
          source_uri TEXT NOT NULL,
          repo_relative_path TEXT NOT NULL,
          source_type TEXT NOT NULL,
          priority TEXT NOT NULL,
          modality TEXT NOT NULL,
          source_exists INTEGER NOT NULL,
          indexed_file_size INTEGER NOT NULL,
          indexed_mtime_ns INTEGER NOT NULL,
          indexed_content_hash TEXT,
          indexed_extractor_hash TEXT NOT NULL,
          indexed_chunker_hash TEXT NOT NULL,
          indexed_embedding_config_hash TEXT NOT NULL,
          indexed_redaction_config_hash TEXT NOT NULL,
          indexed_at TEXT NOT NULL,
          last_checked_at TEXT NOT NULL,
          freshness_status TEXT NOT NULL,
          staleness_reason TEXT,
          source_fingerprint TEXT NOT NULL,
          UNIQUE(context_key, repo_relative_path)
        );
        CREATE TABLE IF NOT EXISTS chunks (
          chunk_id TEXT PRIMARY KEY,
          source_id TEXT NOT NULL,
          context_key TEXT NOT NULL,
          repo_relative_path TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          line_start INTEGER NOT NULL,
          line_end INTEGER NOT NULL,
          heading_path TEXT NOT NULL,
          content TEXT NOT NULL,
          chunk_hash TEXT NOT NULL,
          chunk_fingerprint TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(source_id, chunk_index)
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
          content,
          chunk_id UNINDEXED,
          source_id UNINDEXED,
          context_key UNINDEXED,
          repo_relative_path UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS embedding_profiles (
          embedding_profile_id TEXT PRIMARY KEY,
          provider TEXT NOT NULL,
          model TEXT NOT NULL,
          dimensions INTEGER NOT NULL,
          metric TEXT NOT NULL,
          config_hash TEXT NOT NULL UNIQUE,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS vectors (
          vector_id TEXT PRIMARY KEY,
          chunk_id TEXT NOT NULL,
          context_key TEXT NOT NULL,
          embedding_profile_id TEXT NOT NULL,
          modality TEXT NOT NULL,
          dimensions INTEGER NOT NULL,
          vector_blob BLOB NOT NULL,
          vector_hash TEXT NOT NULL,
          created_at TEXT NOT NULL,
          UNIQUE(chunk_id, embedding_profile_id)
        );
        CREATE TABLE IF NOT EXISTS ingest_runs (
          ingest_run_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS freshness_snapshots (
          snapshot_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          checked_at TEXT NOT NULL,
          mode TEXT NOT NULL,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reset_plans (
          plan_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          mode TEXT NOT NULL,
          created_at TEXT NOT NULL,
          applied_at TEXT,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS worker_runs (
          worker_run_id TEXT PRIMARY KEY,
          context_key TEXT NOT NULL,
          started_at TEXT NOT NULL,
          finished_at TEXT,
          status TEXT NOT NULL,
          summary_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS worker_locks (
          context_key TEXT PRIMARY KEY,
          worker_run_id TEXT NOT NULL,
          acquired_at TEXT NOT NULL,
          heartbeat_at TEXT NOT NULL
        );
        """
    )
    con.executescript(
        """
        CREATE INDEX IF NOT EXISTS idx_sources_context_path ON sources(context_key, repo_relative_path);
        CREATE INDEX IF NOT EXISTS idx_sources_context_freshness ON sources(context_key, freshness_status, priority, repo_relative_path);
        CREATE INDEX IF NOT EXISTS idx_sources_context_priority_status ON sources(context_key, priority, freshness_status, repo_relative_path);
        CREATE INDEX IF NOT EXISTS idx_sources_context_fingerprint ON sources(context_key, source_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_sources_context_mtime ON sources(context_key, indexed_mtime_ns);
        CREATE INDEX IF NOT EXISTS idx_sources_scope_lookup ON sources(tenant_slug, namespace_slug, corpus_slug, scope_slug, repo_relative_path);
        CREATE INDEX IF NOT EXISTS idx_chunks_source_line ON chunks(source_id, line_start, line_end);
        CREATE INDEX IF NOT EXISTS idx_chunks_context_path ON chunks(context_key, repo_relative_path);
        CREATE INDEX IF NOT EXISTS idx_chunks_context_line_lookup ON chunks(context_key, repo_relative_path, line_start, line_end);
        CREATE INDEX IF NOT EXISTS idx_chunks_fingerprint ON chunks(context_key, chunk_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_vectors_chunk_profile ON vectors(chunk_id, embedding_profile_id);
        CREATE INDEX IF NOT EXISTS idx_vectors_context_profile ON vectors(context_key, embedding_profile_id);
        CREATE INDEX IF NOT EXISTS idx_vectors_profile_modality ON vectors(embedding_profile_id, context_key, modality);
        CREATE INDEX IF NOT EXISTS idx_ingest_runs_context_started ON ingest_runs(context_key, started_at);
        CREATE INDEX IF NOT EXISTS idx_freshness_context_checked ON freshness_snapshots(context_key, checked_at);
        CREATE INDEX IF NOT EXISTS idx_worker_runs_context_status ON worker_runs(context_key, status, started_at);
        """
    )
    con.execute("INSERT OR REPLACE INTO database_metadata(key, value) VALUES (?, ?)", ("schema_version", SCHEMA_VERSION))
    con.commit()


def ensure_context(con: sqlite3.Connection, rt: Runtime) -> str:
    existing = con.execute("SELECT scope_id FROM contexts WHERE context_key = ?", (rt.context["context_key"],)).fetchone()
    now = utc_now()
    if existing:
        con.execute("UPDATE contexts SET updated_at = ? WHERE scope_id = ?", (now, existing["scope_id"]))
        return str(existing["scope_id"])
    scope_id = uuid7()
    con.execute(
        """
        INSERT INTO contexts(scope_id, tenant_slug, namespace_slug, corpus_slug, scope_slug, context_key, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            scope_id,
            rt.context["tenant_slug"],
            rt.context["namespace_slug"],
            rt.context["corpus_slug"],
            rt.context["scope_slug"],
            rt.context["context_key"],
            now,
            now,
        ),
    )
    return scope_id


def rel_path(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.expanduser().resolve().as_posix()


def scope_definition(rt: Runtime, scope: str) -> dict[str, Any]:
    defs = rt.config["context_index"].get("scopes", {}).get("definitions", {})
    if scope not in defs:
        raise ContextIndexError("UNSUPPORTED_SCOPE", f"context-index scope is not configured: {scope}")
    definition = dict(defs[scope])
    if str(definition.get("type", "")) == "global":
        raise ContextIndexError("UNSUPPORTED_SCOPE", "context-index global scope has been removed")
    repo_root = rt.repo_root.resolve()
    for root_value in definition.get("roots") or []:
        root = Path(str(root_value)).expanduser()
        base = root if root.is_absolute() else rt.repo_root / root
        try:
            base.resolve().relative_to(repo_root)
        except ValueError as exc:
            raise ContextIndexError("UNSUPPORTED_SCOPE", f"context-index scope root is outside the repository: {root_value}") from exc
    return definition


def matches_any(value: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if pattern == "**/*" and value:
            return True
        if fnmatch.fnmatch(value, pattern) or fnmatch.fnmatch(Path(value).name, pattern):
            return True
    return False


def is_excluded(rel: str, excludes: list[str]) -> bool:
    normalized = rel.replace("\\", "/")
    parts = normalized.split("/")
    if any(part in {".git", "node_modules", "__pycache__", ".venv", "venv"} for part in parts):
        return True
    return matches_any(normalized, excludes)


def priority_for(rel: str) -> str:
    return "high" if matches_any(rel, HIGH_PRIORITY_PATTERNS) else "normal"


def source_type_for(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower().lstrip(".")
    if path.name == "SKILL.md":
        return "skill", "text"
    if suffix in {"md", "mdx", "rst", "txt"}:
        return "doc", "text"
    if suffix in {"json", "yaml", "yml", "toml", "ini"}:
        return "config", "text"
    if suffix in {"html", "htm", "xml", "css", "scss"}:
        return "markup", "text"
    if suffix in {"png", "jpg", "jpeg", "webp", "gif"}:
        return "image", "image"
    if suffix in {"py", "js", "jsx", "ts", "tsx", "java", "go", "rs", "c", "cpp", "h", "cs", "php", "rb", "swift", "kt", "sql", "sh", "bash", "zsh", "ps1"}:
        return "code", "code"
    return "other", "text"


def inventory(rt: Runtime, include_excluded: bool = False) -> list[dict[str, Any]]:
    definition = scope_definition(rt, rt.scope)
    roots = definition.get("roots") or ["."]
    includes = [str(v) for v in definition.get("include", ["**/*"])]
    excludes = [str(v) for v in definition.get("exclude", DEFAULT_EXCLUDES)]
    max_bytes = int(definition.get("max_file_bytes", 1048576))
    found: dict[str, dict[str, Any]] = {}
    for root_value in roots:
        root = Path(str(root_value)).expanduser()
        base = root if root.is_absolute() else rt.repo_root / root
        if not base.exists():
            continue
        paths = [base] if base.is_file() else [p for p in base.rglob("*") if p.is_file()]
        for path in paths:
            rel = rel_path(rt.repo_root, path)
            excluded = is_excluded(rel, excludes)
            included = matches_any(rel, includes) or any(fnmatch.fnmatch(path.name, pat) for pat in includes)
            if not included and not (include_excluded and excluded):
                continue
            if excluded and not include_excluded:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            if stat.st_size > max_bytes:
                if include_excluded:
                    found[rel] = {"path": rel, "status": "excluded", "reason": "max_file_bytes", "size": stat.st_size}
                continue
            source_type, modality = source_type_for(path)
            found[rel] = {
                "path": rel,
                "absolute": str(path.resolve()),
                "status": "included" if not excluded else "excluded",
                "reason": None if not excluded else "exclude_pattern",
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "priority": priority_for(rel),
                "source_type": source_type,
                "modality": modality,
            }
    return sorted(found.values(), key=lambda item: (0 if item.get("priority") == "high" else 1, item["path"]))


def read_extract_text(path: Path, source_type: str, modality: str) -> str:
    if modality == "image":
        try:
            stat = path.stat()
            return f"Image asset: {path.name}\nBytes: {stat.st_size}\n"
        except OSError:
            return f"Image asset: {path.name}\n"
    return path.read_text(encoding="utf-8", errors="replace")


def chunk_text(text: str, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    lines = text.splitlines()
    if not lines:
        lines = [""]
    target = int(cfg.get("target_lines", 80))
    overlap = int(cfg.get("overlap_lines", 8))
    max_chunks = int(cfg.get("max_chunks_per_file", 500))
    chunks: list[dict[str, Any]] = []
    start = 0
    while start < len(lines) and len(chunks) < max_chunks:
        end = min(len(lines), start + target)
        content = "\n".join(lines[start:end])
        heading = []
        for line in reversed(lines[:end]):
            stripped = line.strip()
            if stripped.startswith("#"):
                heading = [stripped.lstrip("#").strip()]
                break
        chunks.append({"line_start": start + 1, "line_end": end, "heading_path": heading, "content": content})
        if end == len(lines):
            break
        start = max(end - overlap, start + 1)
    return chunks


def embedding_profile(rt: Runtime, con: sqlite3.Connection) -> str:
    emb = rt.config["context_index"].get("embeddings", {})
    provider = str(emb.get("provider") or "local_hash")
    model = str(emb.get("model") or "localsetup-hash-v1")
    dims = int(emb.get("dimensions") or DEFAULT_VECTOR_DIMENSIONS)
    metric = "cosine"
    cfg_hash = stable_json_hash({"provider": provider, "model": model, "dimensions": dims, "metric": metric})
    row = con.execute("SELECT embedding_profile_id FROM embedding_profiles WHERE config_hash = ?", (cfg_hash,)).fetchone()
    if row:
        return str(row["embedding_profile_id"])
    profile_id = uuid7()
    con.execute(
        "INSERT INTO embedding_profiles VALUES (?, ?, ?, ?, ?, ?, ?)",
        (profile_id, provider, model, dims, metric, cfg_hash, utc_now()),
    )
    return profile_id


def vector_for_text(text: str, dimensions: int) -> list[float]:
    values = [0.0] * dimensions
    words = [w for w in text.lower().split() if w]
    if not words:
        words = [text[:64] or "empty"]
    for word in words:
        digest = hashlib.sha256(word.encode("utf-8", errors="replace")).digest()
        idx = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        values[idx] += sign
    norm = math.sqrt(sum(v * v for v in values)) or 1.0
    return [v / norm for v in values]


def openai_compatible_embedding(rt: Runtime, text: str, dimensions: int) -> list[float]:
    emb = rt.config["context_index"].get("embeddings", {})
    endpoint = str(emb.get("endpoint") or os.environ.get("LOCALSETUP_CONTEXT_INDEX_EMBEDDINGS_URL", "")).strip()
    if not endpoint:
        raise ContextIndexError(
            "EMBEDDING_ENDPOINT_MISSING",
            "Embedding provider requires an OpenAI-compatible endpoint.",
            "Set context_index.embeddings.endpoint or LOCALSETUP_CONTEXT_INDEX_EMBEDDINGS_URL.",
        )
    api_key_env = str(emb.get("api_key_env") or "")
    api_key = os.environ.get(api_key_env, "") if api_key_env else os.environ.get("OPENAI_API_KEY", "")
    payload = json.dumps({"model": str(emb.get("model") or ""), "input": text, "encoding_format": "float"}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=int(emb.get("timeout_seconds") or 30)) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        raise ContextIndexError("EMBEDDING_REQUEST_FAILED", str(exc), "Check endpoint, credentials, and local embedding server health.") from exc
    try:
        vector = [float(v) for v in data["data"][0]["embedding"]]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ContextIndexError("EMBEDDING_RESPONSE_INVALID", "Embedding response did not contain data[0].embedding.") from exc
    if len(vector) != dimensions:
        raise ContextIndexError(
            "EMBEDDING_DIMENSION_MISMATCH",
            f"Embedding returned {len(vector)} dimensions but config expects {dimensions}.",
            "Set context_index.embeddings.dimensions to match the provider/model.",
        )
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def embedding_vector(rt: Runtime, text: str, usage: str) -> list[float]:
    emb = rt.config["context_index"].get("embeddings", {})
    dimensions = int(emb.get("dimensions") or DEFAULT_VECTOR_DIMENSIONS)
    prefix_key = "query_prefix" if usage == "query" else "document_prefix"
    prepared = str(emb.get(prefix_key) or "") + text
    provider = str(emb.get("provider") or "local_hash").lower().replace("-", "_")
    if provider == "local_hash":
        return vector_for_text(prepared, dimensions)
    if provider in {"openai_compatible", "openai", "llama_cpp", "llamacpp"}:
        return openai_compatible_embedding(rt, prepared, dimensions)
    raise ContextIndexError(
        "EMBEDDING_PROVIDER_UNSUPPORTED",
        f"Unsupported embedding provider: {provider}",
        "Use local_hash or an OpenAI-compatible HTTP endpoint.",
    )


def pack_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def unpack_vector(blob: bytes) -> list[float]:
    if not blob:
        return []
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def safe_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]{2,}", query.lower())[:20]
    if not terms:
        terms = re.findall(r"[A-Za-z0-9_]", query.lower())[:20]
    return " OR ".join(dict.fromkeys(terms)) or "empty"


def log_event(rt: Runtime, event: str, payload: dict[str, Any]) -> None:
    cfg = rt.config["context_index"].get("logging", {})
    if not bool(cfg.get("enabled", True)):
        return
    path = rt.repo_root / LOG_REL if rt.scope == "repo" else rt.home / ".local/share/localsetup/context-index/logs/context-index.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = int(cfg.get("max_bytes", 10485760))
    max_files = int(cfg.get("max_files", 5))
    if path.exists() and path.stat().st_size > max_bytes:
        for idx in range(max_files - 1, 0, -1):
            src = path.with_suffix(path.suffix + f".{idx}")
            dst = path.with_suffix(path.suffix + f".{idx + 1}")
            if src.exists():
                if idx + 1 > max_files:
                    src.unlink()
                else:
                    os.replace(src, dst)
        os.replace(path, path.with_suffix(path.suffix + ".1"))
    entry = {"ts": utc_now(), "level": "info", "event": event, "context_key": rt.context["context_key"], **payload}
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def source_hash(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def config_hashes(rt: Runtime) -> dict[str, str]:
    ci = rt.config["context_index"]
    return {
        "extractor": stable_json_hash({"version": EXTRACTOR_VERSION, "scope": scope_definition(rt, rt.scope)}),
        "chunker": stable_json_hash({"version": CHUNKER_VERSION, **ci.get("chunking", {})}),
        "embedding": stable_json_hash(ci.get("embeddings", {})),
        "redaction": stable_json_hash(ci.get("security", {})),
    }


def status_for_item(rt: Runtime, row: sqlite3.Row | None, item: dict[str, Any], deep: bool = False) -> dict[str, Any]:
    path = Path(item["absolute"])
    hashes = config_hashes(rt)
    current_hash = None
    reasons: list[str] = []
    if row is None:
        status = "not_indexed"
        reasons.append("missing_db_record")
    else:
        status = "fresh"
        if int(row["indexed_file_size"]) != int(item["size"]):
            reasons.append("size_changed")
        if int(row["indexed_mtime_ns"]) != int(item["mtime_ns"]):
            reasons.append("mtime_ns_changed")
        if row["indexed_extractor_hash"] != hashes["extractor"]:
            reasons.append("extractor_changed")
        if row["indexed_chunker_hash"] != hashes["chunker"]:
            reasons.append("chunker_changed")
        if row["indexed_embedding_config_hash"] != hashes["embedding"]:
            reasons.append("embedding_changed")
        if row["indexed_redaction_config_hash"] != hashes["redaction"]:
            reasons.append("redaction_changed")
        if deep or reasons:
            current_hash = source_hash(path)
            if row["indexed_content_hash"] != current_hash:
                reasons.append("content_hash_changed")
        if reasons:
            status = "changed"
            if any(reason.endswith("_changed") and reason.startswith("embedding") for reason in reasons):
                status = "needs_reembed"
    return {
        "path": item["path"],
        "status": status,
        "reasons": sorted(set(reasons)),
        "priority": item.get("priority", "normal"),
        "source_id": row["source_id"] if row else None,
        "indexed_file_size": row["indexed_file_size"] if row else None,
        "current_file_size": item["size"],
        "indexed_mtime_ns": row["indexed_mtime_ns"] if row else None,
        "current_mtime_ns": item["mtime_ns"],
        "indexed_content_hash": row["indexed_content_hash"] if row else None,
        "current_content_hash": current_hash,
        "indexed_at": row["indexed_at"] if row else None,
        "last_checked_at": utc_now(),
    }


def freshness_payload(rt: Runtime, *, deep: bool = False, include_files: bool = True) -> dict[str, Any]:
    con = connect(rt)
    ensure_context(con, rt)
    items = [item for item in inventory(rt) if item["status"] == "included"]
    by_path = {item["path"]: item for item in items}
    rows = {
        row["repo_relative_path"]: row
        for row in con.execute("SELECT * FROM sources WHERE context_key = ?", (rt.context["context_key"],)).fetchall()
    }
    files: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for rel, item in by_path.items():
        status = status_for_item(rt, rows.get(rel), item, deep=deep)
        files.append(status)
        counts[status["status"]] = counts.get(status["status"], 0) + 1
    for rel, row in rows.items():
        if rel not in by_path:
            status = {
                "path": rel,
                "status": "deleted",
                "reasons": ["source_missing_from_inventory"],
                "priority": "normal",
                "source_id": row["source_id"],
                "indexed_file_size": row["indexed_file_size"],
                "current_file_size": None,
                "indexed_mtime_ns": row["indexed_mtime_ns"],
                "current_mtime_ns": None,
                "indexed_content_hash": row["indexed_content_hash"],
                "current_content_hash": None,
                "indexed_at": row["indexed_at"],
                "last_checked_at": utc_now(),
            }
            files.append(status)
            counts["deleted"] = counts.get("deleted", 0) + 1
    for key in ("fresh", "not_indexed", "changed", "deleted", "needs_reembed", "unknown"):
        counts.setdefault(key, 0)
    direct = [f["path"] for f in files if f["status"] in {"not_indexed", "changed", "deleted", "needs_reembed", "unknown"}]
    snapshot = {
        "ok": True,
        "mode": "deep" if deep else "quick",
        "checked_at": utc_now(),
        "database": str(rt.db_path),
        "contexts": [
            {
                **rt.context,
                "scope": rt.scope,
                "safe_to_use_index": not direct,
                "vector_search_primary": True,
                "summary": counts,
                "agent_guidance": {
                    "use_vector_search_first": True,
                    "read_direct_paths": direct,
                    "do_not_trust_index_for_paths": direct,
                    "recommended_action": "Use vector search for fresh sources. Read listed paths directly before relying on them."
                    if direct
                    else "Use vector search first; indexed sources are fresh for this scope.",
                },
                "files": files if include_files else [],
            }
        ],
    }
    con.execute(
        "INSERT INTO freshness_snapshots VALUES (?, ?, ?, ?, ?)",
        (uuid7(), rt.context["context_key"], utc_now(), snapshot["mode"], json.dumps(counts, sort_keys=True)),
    )
    con.commit()
    return snapshot


def worklist_payload(rt: Runtime) -> dict[str, Any]:
    fresh = freshness_payload(rt, include_files=True)
    files = fresh["contexts"][0]["files"]
    extract = []
    embed = []
    tombstone = []
    for item in files:
        if item["status"] in {"not_indexed", "changed"}:
            extract.append({"path": item["path"], "priority": item.get("priority", "normal"), "reason": item["status"]})
            embed.append({"path": item["path"], "priority": item.get("priority", "normal"), "reason": item["status"]})
        elif item["status"] == "needs_reembed":
            embed.append({"path": item["path"], "priority": item.get("priority", "normal"), "reason": "needs_reembed"})
        elif item["status"] == "deleted":
            tombstone.append({"path": item["path"], "priority": "normal", "reason": "deleted"})
    return {
        "ok": True,
        "context_key": rt.context["context_key"],
        "has_work": bool(extract or embed or tombstone),
        "summary": {"extract": len(extract), "chunk": len(extract), "embed": len(embed), "tombstone": len(tombstone), "repair": 0},
        "extract": extract,
        "chunk": extract,
        "embed": embed,
        "delete_or_tombstone": tombstone,
        "agent_guidance": fresh["contexts"][0]["agent_guidance"],
    }


def upsert_source_chunks(rt: Runtime, con: sqlite3.Connection, scope_id: str, item: dict[str, Any], profile_id: str) -> dict[str, int]:
    now = utc_now()
    path = Path(item["absolute"])
    text = read_extract_text(path, item["source_type"], item["modality"])
    content_hash = source_hash(path)
    hashes = config_hashes(rt)
    source_fingerprint = stable_json_hash({"context": rt.context["context_key"], "path": item["path"], "hash": content_hash})
    existing = con.execute(
        "SELECT source_id FROM sources WHERE context_key = ? AND repo_relative_path = ?",
        (rt.context["context_key"], item["path"]),
    ).fetchone()
    source_id = existing["source_id"] if existing else uuid7()
    values = (
        source_id,
        scope_id,
        rt.context["context_key"],
        rt.context["tenant_slug"],
        rt.context["namespace_slug"],
        rt.context["corpus_slug"],
        rt.context["scope_slug"],
        item["absolute"],
        item["path"],
        item["source_type"],
        item["priority"],
        item["modality"],
        1,
        item["size"],
        item["mtime_ns"],
        content_hash,
        hashes["extractor"],
        hashes["chunker"],
        hashes["embedding"],
        hashes["redaction"],
        now,
        now,
        "fresh",
        None,
        source_fingerprint,
    )
    con.execute(
        """
        INSERT INTO sources VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(context_key, repo_relative_path) DO UPDATE SET
          source_uri=excluded.source_uri, source_type=excluded.source_type, priority=excluded.priority,
          modality=excluded.modality, source_exists=1, indexed_file_size=excluded.indexed_file_size,
          indexed_mtime_ns=excluded.indexed_mtime_ns, indexed_content_hash=excluded.indexed_content_hash,
          indexed_extractor_hash=excluded.indexed_extractor_hash, indexed_chunker_hash=excluded.indexed_chunker_hash,
          indexed_embedding_config_hash=excluded.indexed_embedding_config_hash,
          indexed_redaction_config_hash=excluded.indexed_redaction_config_hash,
          indexed_at=excluded.indexed_at, last_checked_at=excluded.last_checked_at,
          freshness_status='fresh', staleness_reason=NULL, source_fingerprint=excluded.source_fingerprint
        """,
        values,
    )
    con.execute("DELETE FROM chunk_fts WHERE source_id = ?", (source_id,))
    old_chunks = con.execute("SELECT chunk_id FROM chunks WHERE source_id = ?", (source_id,)).fetchall()
    for old in old_chunks:
        con.execute("DELETE FROM vectors WHERE chunk_id = ?", (old["chunk_id"],))
    con.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
    chunks = chunk_text(text, rt.config["context_index"].get("chunking", {}))
    dims = int(rt.config["context_index"].get("embeddings", {}).get("dimensions") or DEFAULT_VECTOR_DIMENSIONS)
    for idx, chunk in enumerate(chunks):
        chunk_id = uuid7()
        chunk_hash = sha256_text(chunk["content"])
        chunk_fingerprint = stable_json_hash({"source": source_fingerprint, "index": idx, "hash": chunk_hash})
        con.execute(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                chunk_id,
                source_id,
                rt.context["context_key"],
                item["path"],
                idx,
                chunk["line_start"],
                chunk["line_end"],
                json.dumps(chunk["heading_path"]),
                chunk["content"],
                chunk_hash,
                chunk_fingerprint,
                now,
                now,
            ),
        )
        con.execute(
            "INSERT INTO chunk_fts(content, chunk_id, source_id, context_key, repo_relative_path) VALUES (?, ?, ?, ?, ?)",
            (chunk["content"], chunk_id, source_id, rt.context["context_key"], item["path"]),
        )
        vector = embedding_vector(rt, chunk["content"], "document")
        blob = pack_vector(vector)
        con.execute(
            "INSERT INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid7(),
                chunk_id,
                rt.context["context_key"],
                profile_id,
                item["modality"],
                dims,
                blob,
                sha256_bytes(blob),
                now,
            ),
        )
    return {"sources": 1, "chunks": len(chunks), "vectors": len(chunks)}


def ingest(rt: Runtime, changed_only: bool = False) -> dict[str, Any]:
    con = connect(rt)
    scope_id = ensure_context(con, rt)
    profile_id = embedding_profile(rt, con)
    con.commit()
    fresh = freshness_payload(rt, deep=False, include_files=True)
    run_id = uuid7()
    now = utc_now()
    con.execute("INSERT INTO ingest_runs VALUES (?, ?, ?, ?, ?, ?)", (run_id, rt.context["context_key"], now, None, "running", "{}"))
    statuses = {item["path"]: item for item in fresh["contexts"][0]["files"]}
    items = [item for item in inventory(rt) if item["status"] == "included"]
    totals = {"sources": 0, "chunks": 0, "vectors": 0, "skipped": 0, "tombstoned": 0}
    for item in items:
        status = statuses.get(item["path"], {}).get("status")
        if changed_only and status == "fresh":
            totals["skipped"] += 1
            continue
        if status == "fresh":
            totals["skipped"] += 1
            continue
        counts = upsert_source_chunks(rt, con, scope_id, item, profile_id)
        for key, value in counts.items():
            totals[key] += value
    for item in fresh["contexts"][0]["files"]:
        if item["status"] == "deleted" and item.get("source_id"):
            con.execute(
                "UPDATE sources SET source_exists=0, freshness_status='deleted', staleness_reason='source_missing_from_filesystem', last_checked_at=? WHERE source_id=?",
                (utc_now(), item["source_id"]),
            )
            totals["tombstoned"] += 1
    con.execute(
        "UPDATE ingest_runs SET finished_at=?, status=?, summary_json=? WHERE ingest_run_id=?",
        (utc_now(), "completed", json.dumps(totals, sort_keys=True), run_id),
    )
    con.commit()
    log_event(rt, "ingest.completed", {"run_id": run_id, "summary": totals})
    return {"ok": True, "command": "ingest", "ingest_run_id": run_id, "context_key": rt.context["context_key"], "summary": totals}


def search(rt: Runtime, query: str, top_k: int, mode: str) -> dict[str, Any]:
    con = connect(rt)
    max_top = int(rt.config["context_index"].get("retrieval", {}).get("max_top_k", 50))
    top = min(top_k, max_top)
    dims = int(rt.config["context_index"].get("embeddings", {}).get("dimensions") or DEFAULT_VECTOR_DIMENSIONS)
    query_vector = embedding_vector(rt, query, "query")
    weights = rt.config["context_index"].get("retrieval", {}).get("hybrid", {})
    lexical_weight = float(weights.get("lexical_weight", 0.35))
    vector_weight = float(weights.get("vector_weight", 0.65))
    scores: dict[str, dict[str, Any]] = {}
    if mode in {"lexical", "hybrid"}:
        lexical_rows = con.execute(
            """
            SELECT c.*, s.source_type, s.modality, s.freshness_status, s.staleness_reason, s.indexed_content_hash,
                   s.indexed_at, s.indexed_mtime_ns,
                   bm25(chunk_fts) AS rank_score
            FROM chunk_fts
            JOIN chunks c ON c.chunk_id = chunk_fts.chunk_id
            JOIN sources s ON s.source_id = c.source_id
            WHERE chunk_fts MATCH ? AND c.context_key = ?
            LIMIT ?
            """,
            (safe_fts_query(query), rt.context["context_key"], top * 5),
        ).fetchall()
        for row in lexical_rows:
            lexical = 1.0 / (1.0 + abs(float(row["rank_score"])))
            scores.setdefault(row["chunk_id"], {"row": row, "lexical_score": 0.0, "vector_score": 0.0})
            scores[row["chunk_id"]]["lexical_score"] = max(scores[row["chunk_id"]]["lexical_score"], lexical)
    if mode in {"vector", "hybrid"}:
        rows = con.execute(
            """
            SELECT c.*, s.source_type, s.modality, s.freshness_status, s.staleness_reason, s.indexed_content_hash,
                   s.indexed_at, s.indexed_mtime_ns,
                   v.vector_blob
            FROM vectors v
            JOIN chunks c ON c.chunk_id = v.chunk_id
            JOIN sources s ON s.source_id = c.source_id
            WHERE v.context_key = ?
            """,
            (rt.context["context_key"],),
        ).fetchall()
        for row in rows:
            vector_score = max(0.0, cosine(query_vector, unpack_vector(row["vector_blob"])))
            if vector_score <= 0 and mode == "vector":
                continue
            scores.setdefault(row["chunk_id"], {"row": row, "lexical_score": 0.0, "vector_score": 0.0})
            scores[row["chunk_id"]]["vector_score"] = max(scores[row["chunk_id"]]["vector_score"], vector_score)
    ranked = []
    for item in scores.values():
        row = item["row"]
        lex = float(item["lexical_score"])
        vec = float(item["vector_score"])
        score = vec if mode == "vector" else lex if mode == "lexical" else (lex * lexical_weight + vec * vector_weight)
        ranked.append((score, row, lex, vec))
    ranked.sort(key=lambda value: value[0], reverse=True)
    results = []
    inventory_by_path = {item["path"]: item for item in inventory(rt) if item["status"] == "included"}
    source_rows: dict[str, sqlite3.Row] = {}
    for rank, (score, row, lex, vec) in enumerate(ranked[:top], start=1):
        content = str(row["content"])
        source_row = source_rows.get(row["source_id"])
        if source_row is None:
            source_row = con.execute("SELECT * FROM sources WHERE source_id=?", (row["source_id"],)).fetchone()
            source_rows[row["source_id"]] = source_row
        item = inventory_by_path.get(row["repo_relative_path"])
        live_status = status_for_item(rt, source_row, item, deep=False) if item and source_row else None
        stale = (live_status["status"] != "fresh") if live_status else row["freshness_status"] != "fresh"
        staleness_reason = ";".join(live_status["reasons"]) if live_status and live_status["reasons"] else row["staleness_reason"]
        results.append(
            {
                "rank": rank,
                "score": score,
                "hybrid_score": score if mode == "hybrid" else None,
                "vector_score": vec,
                "lexical_score": lex,
                "scope": rt.scope,
                "context_key": rt.context["context_key"],
                "source_type": row["source_type"],
                "status": "UNKNOWN",
                "path": row["repo_relative_path"],
                "line_start": row["line_start"],
                "line_end": row["line_end"],
                "heading_path": json.loads(row["heading_path"] or "[]"),
                "snippet": content[:600],
                "chunk_id": row["chunk_id"],
                "source_hash": row["indexed_content_hash"],
                "chunk_hash": row["chunk_hash"],
                "indexed_at": row["indexed_at"],
                "source_mtime": iso_from_ns(row["indexed_mtime_ns"]),
                "git_commit": None,
                "stale": stale,
                "freshness_status": live_status["status"] if live_status else row["freshness_status"],
                "staleness_reason": staleness_reason,
            }
        )
    return {"ok": True, "query": query, "top_k": top, "mode": mode, "scope": [rt.scope], "results": results}


def lookup(rt: Runtime, chunk_id: str) -> dict[str, Any]:
    con = connect(rt)
    row = con.execute(
        "SELECT c.*, s.source_type, s.freshness_status, s.staleness_reason FROM chunks c JOIN sources s ON s.source_id=c.source_id WHERE c.chunk_id=?",
        (chunk_id,),
    ).fetchone()
    if not row:
        raise ContextIndexError("NOT_FOUND", f"chunk not found: {chunk_id}")
    return {
        "ok": True,
        "chunk": {
            "chunk_id": row["chunk_id"],
            "context_key": row["context_key"],
            "path": row["repo_relative_path"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "source_type": row["source_type"],
            "freshness_status": row["freshness_status"],
            "staleness_reason": row["staleness_reason"],
            "content": row["content"],
        },
    }


def mcp_config(rt: Runtime, transport: str) -> dict[str, Any]:
    server = rt.repo_root / "_localsetup" / "tools" / "context_mcp_server.py"
    return {
        "ok": True,
        "transport": transport,
        "read_only_default": True,
        "server": {
            "command": sys.executable,
            "args": [str(server), "--repo", str(rt.repo_root), "--home", str(rt.home), "--transport", transport],
            "env": {},
        },
        "tools": [
            "context_index_search",
            "context_index_lookup",
            "context_index_stats",
            "context_index_stale",
            "context_index_ingest_plan",
        ],
    }


def stats(rt: Runtime) -> dict[str, Any]:
    con = connect(rt)
    table_counts = {
        name: con.execute(f"SELECT COUNT(*) AS c FROM {name} WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
        for name in ("sources", "chunks", "vectors", "ingest_runs", "freshness_snapshots", "reset_plans", "worker_runs")
    }
    table_counts["contexts"] = con.execute("SELECT COUNT(*) AS c FROM contexts WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
    indexes = [row["name"] for row in con.execute("SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    fts_exists = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='chunk_fts'").fetchone() is not None
    return {
        "ok": True,
        "database": str(rt.db_path),
        "database_bytes": rt.db_path.stat().st_size if rt.db_path.exists() else 0,
        "context": rt.context,
        "schema_version": SCHEMA_VERSION,
        "counts": table_counts,
        "indexes": indexes,
        "fts": {"chunk_fts": fts_exists},
    }


def vector_rebuild_plan(rt: Runtime) -> dict[str, Any]:
    con = connect(rt)
    chunks = con.execute("SELECT COUNT(*) AS c FROM chunks WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
    vectors = con.execute("SELECT COUNT(*) AS c FROM vectors WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
    plan_id = uuid7()
    summary = {"chunks_to_revector": chunks, "existing_vectors": vectors}
    con.execute(
        "INSERT INTO reset_plans VALUES (?, ?, ?, ?, ?, ?)",
        (plan_id, rt.context["context_key"], "vector_rebuild", utc_now(), None, json.dumps(summary, sort_keys=True)),
    )
    con.commit()
    return {"ok": True, "plan_id": plan_id, "mode": "vector_rebuild", "context_key": rt.context["context_key"], "would_rebuild": summary}


def vector_rebuild_apply(rt: Runtime, plan_id: str) -> dict[str, Any]:
    con = connect(rt)
    plan = con.execute(
        "SELECT * FROM reset_plans WHERE plan_id=? AND context_key=? AND mode='vector_rebuild'",
        (plan_id, rt.context["context_key"]),
    ).fetchone()
    if not plan:
        raise ContextIndexError("PLAN_NOT_FOUND", f"vector rebuild plan not found for this context: {plan_id}")
    profile_id = embedding_profile(rt, con)
    dims = int(rt.config["context_index"].get("embeddings", {}).get("dimensions") or DEFAULT_VECTOR_DIMENSIONS)
    rows = con.execute(
        """
        SELECT c.chunk_id, c.content, s.modality
        FROM chunks c
        JOIN sources s ON s.source_id = c.source_id
        WHERE c.context_key = ?
        """,
        (rt.context["context_key"],),
    ).fetchall()
    rebuilt = 0
    for row in rows:
        con.execute("DELETE FROM vectors WHERE chunk_id=? AND embedding_profile_id=?", (row["chunk_id"], profile_id))
        vector = embedding_vector(rt, row["content"], "document")
        blob = pack_vector(vector)
        con.execute(
            "INSERT INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid7(),
                row["chunk_id"],
                rt.context["context_key"],
                profile_id,
                row["modality"],
                dims,
                blob,
                sha256_bytes(blob),
                utc_now(),
            ),
        )
        rebuilt += 1
    con.execute("UPDATE reset_plans SET applied_at=? WHERE plan_id=?", (utc_now(), plan_id))
    con.commit()
    log_event(rt, "vectors.rebuilt", {"plan_id": plan_id, "rebuilt": rebuilt})
    return {"ok": True, "plan_id": plan_id, "rebuilt_vectors": rebuilt, "embedding_profile_id": profile_id}


def prune_plan(rt: Runtime) -> dict[str, Any]:
    con = connect(rt)
    deleted_sources = con.execute(
        "SELECT COUNT(*) AS c FROM sources WHERE context_key=? AND (source_exists=0 OR freshness_status='deleted')",
        (rt.context["context_key"],),
    ).fetchone()["c"]
    orphan_vectors = con.execute(
        "SELECT COUNT(*) AS c FROM vectors WHERE context_key=? AND chunk_id NOT IN (SELECT chunk_id FROM chunks)",
        (rt.context["context_key"],),
    ).fetchone()["c"]
    plan_id = uuid7()
    summary = {"deleted_sources": deleted_sources, "orphan_vectors": orphan_vectors}
    con.execute(
        "INSERT INTO reset_plans VALUES (?, ?, ?, ?, ?, ?)",
        (plan_id, rt.context["context_key"], "prune", utc_now(), None, json.dumps(summary, sort_keys=True)),
    )
    con.commit()
    return {"ok": True, "plan_id": plan_id, "mode": "prune", "context_key": rt.context["context_key"], "would_delete": summary}


def prune_apply(rt: Runtime, plan_id: str) -> dict[str, Any]:
    con = connect(rt)
    plan = con.execute(
        "SELECT * FROM reset_plans WHERE plan_id=? AND context_key=? AND mode='prune'",
        (plan_id, rt.context["context_key"]),
    ).fetchone()
    if not plan:
        raise ContextIndexError("PLAN_NOT_FOUND", f"prune plan not found for this context: {plan_id}")
    source_ids = [
        row["source_id"]
        for row in con.execute(
            "SELECT source_id FROM sources WHERE context_key=? AND (source_exists=0 OR freshness_status='deleted')",
            (rt.context["context_key"],),
        )
    ]
    chunk_ids = [
        row["chunk_id"]
        for row in con.execute(
            f"SELECT chunk_id FROM chunks WHERE source_id IN ({','.join('?' for _ in source_ids)})" if source_ids else "SELECT chunk_id FROM chunks WHERE 0",
            source_ids,
        )
    ]
    for chunk_id in chunk_ids:
        con.execute("DELETE FROM vectors WHERE chunk_id=?", (chunk_id,))
    for source_id in source_ids:
        con.execute("DELETE FROM chunk_fts WHERE source_id=?", (source_id,))
    if source_ids:
        con.execute(f"DELETE FROM chunks WHERE source_id IN ({','.join('?' for _ in source_ids)})", source_ids)
        con.execute(f"DELETE FROM sources WHERE source_id IN ({','.join('?' for _ in source_ids)})", source_ids)
    orphan_vectors = con.execute(
        "DELETE FROM vectors WHERE context_key=? AND chunk_id NOT IN (SELECT chunk_id FROM chunks)",
        (rt.context["context_key"],),
    ).rowcount
    con.execute("UPDATE reset_plans SET applied_at=? WHERE plan_id=?", (utc_now(), plan_id))
    con.commit()
    summary = {"deleted_sources": len(source_ids), "deleted_chunks": len(chunk_ids), "orphan_vectors": orphan_vectors}
    log_event(rt, "prune.applied", {"plan_id": plan_id, "summary": summary})
    return {"ok": True, "plan_id": plan_id, "applied": True, "summary": summary}


def reset_plan(rt: Runtime, mode: str) -> dict[str, Any]:
    con = connect(rt)
    counts = {
        "sources": con.execute("SELECT COUNT(*) AS c FROM sources WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"],
        "chunks": con.execute("SELECT COUNT(*) AS c FROM chunks WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"],
        "vectors": con.execute("SELECT COUNT(*) AS c FROM vectors WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"],
    }
    plan_id = uuid7()
    con.execute(
        "INSERT INTO reset_plans VALUES (?, ?, ?, ?, ?, ?)",
        (plan_id, rt.context["context_key"], mode, utc_now(), None, json.dumps(counts, sort_keys=True)),
    )
    con.commit()
    return {"ok": True, "plan_id": plan_id, "mode": mode, "context_key": rt.context["context_key"], "would_delete": counts}


def reset_apply(rt: Runtime, plan_id: str) -> dict[str, Any]:
    con = connect(rt)
    plan = con.execute("SELECT * FROM reset_plans WHERE plan_id=? AND context_key=?", (plan_id, rt.context["context_key"])).fetchone()
    if not plan:
        raise ContextIndexError("PLAN_NOT_FOUND", f"reset plan not found for this context: {plan_id}")
    source_ids = [row["source_id"] for row in con.execute("SELECT source_id FROM sources WHERE context_key=?", (rt.context["context_key"],))]
    chunk_ids = [row["chunk_id"] for row in con.execute("SELECT chunk_id FROM chunks WHERE context_key=?", (rt.context["context_key"],))]
    for chunk_id in chunk_ids:
        con.execute("DELETE FROM vectors WHERE chunk_id=?", (chunk_id,))
    for source_id in source_ids:
        con.execute("DELETE FROM chunk_fts WHERE source_id=?", (source_id,))
    con.execute("DELETE FROM chunks WHERE context_key=?", (rt.context["context_key"],))
    con.execute("DELETE FROM sources WHERE context_key=?", (rt.context["context_key"],))
    con.execute("UPDATE reset_plans SET applied_at=? WHERE plan_id=?", (utc_now(), plan_id))
    con.commit()
    log_event(rt, "reset.applied", {"plan_id": plan_id})
    return {"ok": True, "plan_id": plan_id, "applied": True}


def worker_nudge(rt: Runtime) -> dict[str, Any]:
    con = connect(rt)
    work = worklist_payload(rt)
    existing = con.execute("SELECT * FROM worker_locks WHERE context_key=?", (rt.context["context_key"],)).fetchone()
    if existing:
        return {"ok": True, "nudged": False, "status": "already_running", "worker_run_id": existing["worker_run_id"], "worklist": work["summary"]}
    if not work["has_work"]:
        return {"ok": True, "nudged": False, "status": "no_work", "worklist": work["summary"]}
    worker_id = uuid7()
    now = utc_now()
    con.execute("INSERT INTO worker_runs VALUES (?, ?, ?, ?, ?, ?)", (worker_id, rt.context["context_key"], now, None, "queued", "{}"))
    con.commit()
    return {"ok": True, "nudged": True, "status": "queued", "worker_run_id": worker_id, "worklist": work["summary"]}


def worker_status(rt: Runtime) -> dict[str, Any]:
    con = connect(rt)
    rows = [dict(row) for row in con.execute("SELECT * FROM worker_runs WHERE context_key=? ORDER BY started_at DESC LIMIT 10", (rt.context["context_key"],))]
    lock = con.execute("SELECT * FROM worker_locks WHERE context_key=?", (rt.context["context_key"],)).fetchone()
    return {"ok": True, "context_key": rt.context["context_key"], "lock": dict(lock) if lock else None, "runs": rows}


def logs_status(rt: Runtime) -> dict[str, Any]:
    repo_log = rt.repo_root / LOG_REL
    global_log = rt.home / ".local/share/localsetup/context-index/logs/context-index.jsonl"
    def stat(path: Path) -> dict[str, Any]:
        return {"path": str(path), "exists": path.exists(), "bytes": path.stat().st_size if path.exists() else 0}
    return {"ok": True, "logs": [stat(repo_log), stat(global_log)]}


def logs_rotate(rt: Runtime) -> dict[str, Any]:
    repo_log = rt.repo_root / LOG_REL
    global_log = rt.home / ".local/share/localsetup/context-index/logs/context-index.jsonl"
    rotated: list[dict[str, Any]] = []
    for path in (repo_log, global_log):
        if not path.exists() or path.stat().st_size == 0:
            rotated.append({"path": str(path), "rotated": False, "reason": "missing_or_empty"})
            continue
        archive = path.with_name(f"{path.name}.{utc_now().replace(':', '').replace('-', '').replace('.', '')}.rotated")
        path.rename(archive)
        rotated.append({"path": str(path), "rotated": True, "archive": str(archive)})
    return {"ok": True, "rotated": rotated}


def rebuild_apply(rt: Runtime, plan_id: str) -> dict[str, Any]:
    reset = reset_apply(rt, plan_id)
    ingest_result = ingest(rt, changed_only=False)
    return {"ok": bool(reset.get("ok") and ingest_result.get("ok")), "plan_id": plan_id, "reset": reset, "ingest": ingest_result}


def config_init(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo).expanduser().resolve()
    home = Path(args.home).expanduser().resolve()
    if args.scope == "global":
        raise ContextIndexError("UNSUPPORTED_SCOPE", "context-index global scope has been removed")
    cfg = default_config(repo_root, home)
    path = repo_root / REPO_CONFIG_REL if args.scope == "repo" else home / GLOBAL_CONFIG_REL
    if path.exists() and not args.force:
        return {"ok": True, "created": False, "path": str(path), "message": "config already exists"}
    if yaml is None:
        raise ContextIndexError("MISSING_DEPENDENCY", "PyYAML is required to write config.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return {"ok": True, "created": True, "path": str(path)}


def forbidden_config_keys(cfg: dict[str, Any], repo_root: Path) -> list[str]:
    ci = cfg.get("context_index")
    if not isinstance(ci, dict):
        return []
    forbidden: list[str] = []
    if "memory" in ci:
        forbidden.append("context_index.memory")
    scopes = ci.get("scopes")
    if isinstance(scopes, dict):
        default_query = scopes.get("default_query")
        if isinstance(default_query, list) and "global" in default_query:
            forbidden.append("context_index.scopes.default_query[global]")
        if "include_global_memory_by_default" in scopes:
            forbidden.append("context_index.scopes.include_global_memory_by_default")
        definitions = scopes.get("definitions")
        if isinstance(definitions, dict):
            repo_resolved = repo_root.resolve()
            for name, definition in definitions.items():
                if name == "global":
                    forbidden.append("context_index.scopes.definitions.global")
                if not isinstance(definition, dict):
                    continue
                if definition.get("type") == "global":
                    forbidden.append(f"context_index.scopes.definitions.{name}.type")
                for root_value in definition.get("roots") or []:
                    root = Path(str(root_value)).expanduser()
                    base = root if root.is_absolute() else repo_root / root
                    try:
                        base.resolve().relative_to(repo_resolved)
                    except ValueError:
                        forbidden.append(f"context_index.scopes.definitions.{name}.roots")
                        break
    return forbidden


def config_validate(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(args.repo).expanduser().resolve()
    home = Path(args.home).expanduser().resolve()
    cfg, loaded = load_config(repo_root, home)
    issues = []
    ci = cfg.get("context_index")
    if not isinstance(ci, dict):
        issues.append("missing context_index mapping")
    else:
        for key in ("storage", "scopes", "freshness", "chunking", "embeddings", "retrieval"):
            if key not in ci:
                issues.append(f"missing context_index.{key}")
    for key in forbidden_config_keys(cfg, repo_root):
        issues.append(f"unsupported removed memory/global context setting: {key}")
    return {"ok": not issues, "loaded": loaded, "issues": issues, "config_hash": stable_json_hash(cfg)}


def agent_preflight(rt: Runtime) -> dict[str, Any]:
    fresh = freshness_payload(rt, include_files=False)
    work = worklist_payload(rt)
    con = connect(rt)
    vector_count = con.execute("SELECT COUNT(*) AS c FROM vectors WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
    return {
        "ok": True,
        "context_key": rt.context["context_key"],
        "database": str(rt.db_path),
        "vector_available": vector_count > 0,
        "freshness": fresh["contexts"][0],
        "worklist": work["summary"],
        "recommended_action": fresh["contexts"][0]["agent_guidance"]["recommended_action"],
    }


def dispatch_multi_scope(args: argparse.Namespace, scopes: list[str]) -> dict[str, Any]:
    runtimes = [runtime(args, scope=scope) for scope in scopes]
    if args.cmd == "agent-preflight":
        payloads = [agent_preflight(rt) for rt in runtimes]
        return {
            "ok": all(payload.get("ok") for payload in payloads),
            "scope": scopes,
            "contexts": [
                {
                    "context_key": payload["context_key"],
                    "database": payload["database"],
                    "vector_available": payload["vector_available"],
                    "freshness": payload["freshness"],
                    "worklist": payload["worklist"],
                    "recommended_action": payload["recommended_action"],
                }
                for payload in payloads
            ],
        }
    if args.cmd == "freshness":
        payloads = [freshness_payload(rt, deep=bool(getattr(args, "deep", False))) for rt in runtimes]
        contexts: list[dict[str, Any]] = []
        for payload in payloads:
            contexts.extend(payload["contexts"])
        return {"ok": all(payload.get("ok") for payload in payloads), "mode": payloads[0]["mode"] if payloads else "quick", "checked_at": utc_now(), "scope": scopes, "contexts": contexts}
    if args.cmd in {"stale", "stale-files"}:
        payloads = [freshness_payload(rt, include_files=True) for rt in runtimes]
        files = [item for payload in payloads for item in payload["contexts"][0]["files"]]
        return {
            "ok": True,
            "scope": scopes,
            "read_direct_paths": [f"{payload['contexts'][0]['scope']}:{item['path']}" for payload in payloads for item in payload["contexts"][0]["files"] if item["status"] in {"not_indexed", "changed", "needs_reembed", "unknown"}],
            "not_indexed_paths": [f["path"] for f in files if f["status"] == "not_indexed"],
            "deleted_paths": [f["path"] for f in files if f["status"] == "deleted"],
            "needs_reembed_paths": [f["path"] for f in files if f["status"] == "needs_reembed"],
        }
    if args.cmd in {"worklist", "plan-ingest"}:
        payloads = [worklist_payload(rt) for rt in runtimes]
        summary = {"extract": 0, "chunk": 0, "embed": 0, "tombstone": 0, "repair": 0}
        for payload in payloads:
            for key in summary:
                summary[key] += int(payload["summary"].get(key, 0))
        return {"ok": True, "scope": scopes, "has_work": any(payload["has_work"] for payload in payloads), "summary": summary, "contexts": payloads}
    if args.cmd in {"ingest", "refresh"}:
        payloads = [ingest(rt, changed_only=args.cmd == "refresh" or bool(getattr(args, "changed_only", False))) for rt in runtimes]
        return {"ok": all(payload.get("ok") for payload in payloads), "scope": scopes, "results": payloads}
    if args.cmd == "search":
        results: list[dict[str, Any]] = []
        for rt in runtimes:
            results.extend(search(rt, args.query, args.top_k, args.mode)["results"])
        results.sort(key=lambda item: item["score"], reverse=True)
        max_top = min(args.top_k, max(int(rt.config["context_index"].get("retrieval", {}).get("max_top_k", 50)) for rt in runtimes))
        for rank, item in enumerate(results[:max_top], start=1):
            item["rank"] = rank
        return {"ok": True, "query": args.query, "top_k": max_top, "mode": args.mode, "scope": scopes, "results": results[:max_top]}
    if args.cmd == "worker" and args.worker_cmd in {"nudge", "status", "run"}:
        handlers = {"nudge": worker_nudge, "status": worker_status, "run": lambda rt: ingest(rt, changed_only=True)}
        payloads = [handlers[args.worker_cmd](rt) for rt in runtimes]
        return {"ok": all(payload.get("ok") for payload in payloads), "scope": scopes, "results": payloads}
    if args.cmd == "stats":
        payloads = [stats(rt) for rt in runtimes]
        return {"ok": all(payload.get("ok") for payload in payloads), "scope": scopes, "contexts": payloads}
    raise ContextIndexError("MULTI_SCOPE_UNSUPPORTED", f"Command does not support multiple scopes: {args.cmd}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="context_index")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--source-root")
    parser.add_argument("--home", default=str(Path.home()))
    sub = parser.add_subparsers(dest="cmd", required=True)
    cfg = sub.add_parser("config")
    cfg_sub = cfg.add_subparsers(dest="config_cmd", required=True)
    init_p = cfg_sub.add_parser("init")
    init_p.add_argument("--scope", choices=["repo"], default="repo")
    init_p.add_argument("--force", action="store_true")
    init_p.add_argument("--json", action="store_true", default=True)
    validate_p = cfg_sub.add_parser("validate")
    validate_p.add_argument("--json", action="store_true", default=True)
    for name in (
        "doctor",
        "agent-preflight",
        "freshness",
        "stale",
        "stale-files",
        "worklist",
        "plan-ingest",
        "inventory",
        "ingest",
        "refresh",
        "stats",
        "prune",
        "reset",
        "rebuild",
        "vector-rebuild",
        "worker",
        "logs",
        "lookup",
        "mcp",
    ):
        p = sub.add_parser(name)
        p.add_argument("--scope", default="repo")
    sub.add_parser("search").add_argument("query")
    parser.add_argument("--json", action="store_true", default=True)
    # argparse cannot add shared options to already-created subcommands after the fact.
    for action in sub.choices.values():
        if not any(opt.dest == "json" for opt in action._actions):
            action.add_argument("--json", action="store_true", default=True)
    sub.choices["freshness"].add_argument("--deep", action="store_true")
    sub.choices["freshness"].add_argument("--quick", action="store_true")
    sub.choices["inventory"].add_argument("--show-excludes", action="store_true")
    sub.choices["ingest"].add_argument("--with-vectors", action="store_true")
    sub.choices["ingest"].add_argument("--changed-only", action="store_true")
    sub.choices["reset"].add_argument("reset_cmd", choices=["plan", "apply"])
    sub.choices["reset"].add_argument("--plan")
    sub.choices["reset"].add_argument("--mode", default="context_full")
    sub.choices["prune"].add_argument("prune_cmd", choices=["plan", "apply"])
    sub.choices["prune"].add_argument("--plan")
    sub.choices["rebuild"].add_argument("rebuild_cmd", choices=["plan", "apply"])
    sub.choices["rebuild"].add_argument("--plan")
    sub.choices["vector-rebuild"].add_argument("vector_rebuild_cmd", choices=["plan", "apply"])
    sub.choices["vector-rebuild"].add_argument("--plan")
    sub.choices["worker"].add_argument("worker_cmd", choices=["nudge", "status", "run"])
    sub.choices["logs"].add_argument("logs_cmd", nargs="?", choices=["status", "rotate"], default="status")
    sub.choices["lookup"].add_argument("--chunk-id", required=True)
    sub.choices["mcp"].add_argument("mcp_cmd", choices=["config", "serve"])
    sub.choices["mcp"].add_argument("--transport", default="stdio", choices=["stdio"])
    sub.choices["search"].add_argument("--scope", default="repo")
    sub.choices["search"].add_argument("--mode", choices=["vector", "lexical", "hybrid"], default="hybrid")
    sub.choices["search"].add_argument("--top-k", type=int, default=10)
    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.cmd == "config":
        if args.config_cmd == "init":
            return config_init(args)
        if args.config_cmd == "validate":
            return config_validate(args)
    scope = getattr(args, "scope", "repo")
    scopes = parse_scopes(scope)
    if len(scopes) > 1:
        return dispatch_multi_scope(args, scopes)
    rt = runtime(args, scope=scope)
    if args.cmd == "doctor":
        con = connect(rt)
        vector_count = con.execute("SELECT COUNT(*) AS c FROM vectors WHERE context_key=?", (rt.context["context_key"],)).fetchone()["c"]
        return {"ok": True, "database": str(rt.db_path), "context": rt.context, "schema_version": SCHEMA_VERSION, "vectors": vector_count}
    if args.cmd == "agent-preflight":
        return agent_preflight(rt)
    if args.cmd == "freshness":
        return freshness_payload(rt, deep=bool(getattr(args, "deep", False)))
    if args.cmd in {"stale", "stale-files"}:
        fresh = freshness_payload(rt, include_files=True)
        files = fresh["contexts"][0]["files"]
        return {
            "ok": True,
            "scope": [rt.scope],
            "read_direct_paths": [f["path"] for f in files if f["status"] in {"not_indexed", "changed", "needs_reembed", "unknown"}],
            "not_indexed_paths": [f["path"] for f in files if f["status"] == "not_indexed"],
            "deleted_paths": [f["path"] for f in files if f["status"] == "deleted"],
            "needs_reembed_paths": [f["path"] for f in files if f["status"] == "needs_reembed"],
        }
    if args.cmd in {"worklist", "plan-ingest"}:
        return worklist_payload(rt)
    if args.cmd == "inventory":
        return {"ok": True, "context": rt.context, "files": inventory(rt, include_excluded=bool(getattr(args, "show_excludes", False)))}
    if args.cmd == "ingest":
        return ingest(rt, changed_only=bool(getattr(args, "changed_only", False)))
    if args.cmd == "refresh":
        return ingest(rt, changed_only=True)
    if args.cmd == "search":
        return search(rt, args.query, args.top_k, args.mode)
    if args.cmd == "lookup":
        return lookup(rt, args.chunk_id)
    if args.cmd == "stats":
        return stats(rt)
    if args.cmd == "mcp":
        if args.mcp_cmd == "config":
            return mcp_config(rt, args.transport)
        raise ContextIndexError(
            "MCP_SERVER_OPTIONAL",
            "MCP serving is optional and requires `_localsetup/tools/context_mcp_server.py` with the MCP Python SDK installed.",
            "Use `context-index mcp config` for client configuration or install the MCP Python SDK before serving.",
        )
    if args.cmd == "reset":
        return reset_plan(rt, args.mode) if args.reset_cmd == "plan" else reset_apply(rt, args.plan or "")
    if args.cmd == "prune":
        return prune_plan(rt) if args.prune_cmd == "plan" else prune_apply(rt, args.plan or "")
    if args.cmd == "rebuild":
        if args.rebuild_cmd == "plan":
            return reset_plan(rt, "context_full")
        return rebuild_apply(rt, args.plan or "")
    if args.cmd == "vector-rebuild":
        return vector_rebuild_plan(rt) if args.vector_rebuild_cmd == "plan" else vector_rebuild_apply(rt, args.plan or "")
    if args.cmd == "worker":
        if args.worker_cmd == "nudge":
            return worker_nudge(rt)
        if args.worker_cmd == "status":
            return worker_status(rt)
        if args.worker_cmd == "run":
            return ingest(rt, changed_only=True)
    if args.cmd == "logs":
        return logs_rotate(rt) if args.logs_cmd == "rotate" else logs_status(rt)
    raise ContextIndexError("UNKNOWN_COMMAND", f"unsupported command: {args.cmd}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = dispatch(args)
        json_print(payload)
        return 0 if payload.get("ok", False) else 1
    except Exception as exc:
        json_print(error_payload(args.cmd if hasattr(args, "cmd") else "context-index", exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

import sqlite3

from .common import SCHEMA_VERSION, Runtime, utc_now, uuid7

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

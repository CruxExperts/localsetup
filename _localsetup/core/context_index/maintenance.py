import json
import sqlite3
from pathlib import Path
from typing import Any

from .chunking import chunk_text, read_extract_text
from .common import CHUNKER_VERSION, EXTRACTOR_VERSION, DEFAULT_VECTOR_DIMENSIONS, Runtime, sha256_bytes, sha256_text, stable_json_hash, utc_now, uuid7
from .config import scope_definition
from .embeddings import embedding_profile, embedding_vector, pack_vector
from .inventory import inventory
from .logs import log_event, source_hash
from .storage import connect, ensure_context

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

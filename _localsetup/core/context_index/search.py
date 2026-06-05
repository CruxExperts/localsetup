import json
import sqlite3
from typing import Any

from .common import DEFAULT_VECTOR_DIMENSIONS, Runtime, iso_from_ns
from .embeddings import cosine, embedding_vector, safe_fts_query, unpack_vector
from .inventory import inventory
from .maintenance import status_for_item
from .storage import connect

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

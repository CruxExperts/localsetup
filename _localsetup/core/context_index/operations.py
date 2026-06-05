import argparse
import json
from pathlib import Path
from typing import Any

from .common import LOG_REL, SCHEMA_VERSION, ContextIndexError, Runtime, sha256_bytes, stable_json_hash, utc_now, uuid7
from .config import load_config, parse_scopes, read_yaml, runtime, scope_definition
from .embeddings import DEFAULT_VECTOR_DIMENSIONS, embedding_profile, embedding_vector, pack_vector
from .inventory import inventory
from .logs import log_event
from .maintenance import freshness_payload, ingest, worklist_payload
from .mcp import mcp_config
from .search import lookup, search
from .storage import connect

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

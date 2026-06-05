import argparse
from pathlib import Path
from typing import Any

from .common import SCHEMA_VERSION, ContextIndexError, error_payload, json_print
from .config import parse_scopes, runtime
from .inventory import inventory
from .maintenance import freshness_payload, ingest, worklist_payload
from .mcp import mcp_config
from .operations import (
    agent_preflight,
    config_init,
    config_validate,
    dispatch_multi_scope,
    logs_rotate,
    logs_status,
    prune_apply,
    prune_plan,
    rebuild_apply,
    reset_apply,
    reset_plan,
    stats,
    vector_rebuild_apply,
    vector_rebuild_plan,
    worker_nudge,
    worker_status,
)
from .search import lookup, search
from .storage import connect

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

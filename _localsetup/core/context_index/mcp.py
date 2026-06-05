import sys
from typing import Any

from .common import Runtime

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

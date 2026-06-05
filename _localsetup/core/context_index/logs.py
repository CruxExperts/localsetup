import json
import os
from pathlib import Path
from typing import Any

from .common import LOG_REL, Runtime, sha256_bytes, utc_now

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

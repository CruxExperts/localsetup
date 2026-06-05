from pathlib import Path
from typing import Any

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

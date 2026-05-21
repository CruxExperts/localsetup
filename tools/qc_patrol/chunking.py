from __future__ import annotations


def chunk_text(name: str, text: str, max_bytes: int) -> list[dict[str, str | int]]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    encoded = text.encode("utf-8")
    chunks: list[dict[str, str | int]] = []
    start = 0
    index = 0
    while start < len(encoded):
        end = min(start + max_bytes, len(encoded))
        while end > start:
            try:
                body = encoded[start:end].decode("utf-8")
                break
            except UnicodeDecodeError:
                end -= 1
        else:
            raise ValueError("unable to split text on UTF-8 boundary")
        chunks.append({"name": name, "index": index, "text": body, "bytes": len(body.encode("utf-8"))})
        start = end
        index += 1
    return chunks or [{"name": name, "index": 0, "text": "", "bytes": 0}]

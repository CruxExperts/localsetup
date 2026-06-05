import hashlib
import math
import os
import re
import sqlite3
import struct

import requests

from .common import DEFAULT_VECTOR_DIMENSIONS, ContextIndexError, Runtime, sha256_bytes, stable_json_hash, utc_now, uuid7

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
    payload = {"model": str(emb.get("model") or ""), "input": text, "encoding_format": "float"}
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.post(endpoint, json=payload, headers=headers, timeout=int(emb.get("timeout_seconds") or 30))
        response.raise_for_status()
        data = response.json()
    except requests.RequestException as exc:
        raise ContextIndexError("EMBEDDING_REQUEST_FAILED", str(exc), "Check endpoint, credentials, and local embedding server health.") from exc
    except ValueError as exc:
        raise ContextIndexError("EMBEDDING_RESPONSE_INVALID", "Embedding response was not valid JSON.") from exc
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

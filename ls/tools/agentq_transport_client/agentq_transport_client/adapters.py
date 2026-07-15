#!/usr/bin/env python3
# Purpose: Transport adapter interface pull_new / push (spec Part 11).
# Created: 2026-03-09
# Last updated: 2026-03-09

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator, Protocol

__all__ = [
    "TransportAdapter",
    "FileDropAdapter",
    "MailAdapterStub",
    "StubDriveAdapter",
    "StubTelegramAdapter",
    "ADAPTER_REGISTRY",
    "get_adapter",
    "file_drop_pull_iter",
    "file_drop_push_armored",
]


class TransportAdapter(Protocol):
    """pull_new yields (raw_blob_bytes, metadata dict); push returns transport_ref str."""

    def pull_new(self) -> Iterator[tuple[bytes, dict[str, Any]]]:
        ...

    def push(self, blob_bytes: bytes, metadata: dict[str, Any]) -> str:
        ...


def file_drop_pull_iter(
    roots: list[Path],
    sealed_extension: str = ".agentq.asc",
) -> Iterator[tuple[bytes, dict[str, Any]]]:
    """Yield armored text as bytes and metadata path for each sealed file (no claim)."""
    from agentq_transport_client.file_drop import iter_candidates

    for sealed, ready in iter_candidates(roots, sealed_extension):
        yield sealed.read_bytes(), {
            "path": str(sealed),
            "ready": str(ready),
            "transport": "file_drop",
        }


class FileDropAdapter:
    """
    Part 11 TransportAdapter-style wrapper over file_drop_pull_iter + file_drop_push_armored.
    """

    def __init__(
        self,
        roots: list[Path],
        out_dir: Path,
        sealed_extension: str = ".agentq.asc",
    ):
        self.roots = [Path(p) for p in roots]
        self.out_dir = Path(out_dir)
        self.sealed_extension = sealed_extension

    def pull_new(self) -> Iterator[tuple[bytes, dict[str, Any]]]:
        return file_drop_pull_iter(self.roots, self.sealed_extension)

    def push(self, blob_bytes: bytes, metadata: dict[str, Any]) -> str:
        stem = str(metadata.get("stem", "payload"))
        return file_drop_push_armored(
            blob_bytes.decode("utf-8") if isinstance(blob_bytes, bytes) else str(blob_bytes),
            self.out_dir,
            stem,
        )


class StubDriveAdapter(FileDropAdapter):
    """
    Google Drive / Dropbox via sync folder only (Part 17 API deferred).
    Same as file_drop: roots are synced directories.
    """

    pass


class StubTelegramAdapter:
    """Placeholder; Part 17 IM adapter."""

    def pull_new(self) -> Iterator[tuple[bytes, dict[str, Any]]]:
        return iter(())

    def push(self, blob_bytes: bytes, metadata: dict[str, Any]) -> str:
        raise NotImplementedError("Telegram adapter not implemented; use file_drop or mail")


ADAPTER_REGISTRY: dict[str, type] = {
    "file_drop": FileDropAdapter,
    "drive_sync": StubDriveAdapter,
    "dropbox_sync": StubDriveAdapter,
    "telegram": StubTelegramAdapter,
    "mail": MailAdapterStub,
}


def get_adapter(name: str, **kwargs: Any) -> Any:
    """Construct adapter by name; kwargs passed to constructor (e.g. roots, out_dir)."""
    cls = ADAPTER_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown adapter: {name}")
    return cls(**kwargs)  # type: ignore[misc]


class MailAdapterStub:
    """
    Placeholder implementing Protocol; real mail uses mail_pull_and_promote / mail_ship_agentq_outer.
    """

    def pull_new(self) -> Iterator[tuple[bytes, dict[str, Any]]]:
        return iter(())

    def push(self, blob_bytes: bytes, metadata: dict[str, Any]) -> str:
        raise NotImplementedError("use mail_ship_agentq_outer or CLI ship-mail")


def file_drop_push_armored(
    armored: str,
    out_dir: Path,
    stem: str,
) -> str:
    """Write armored blob + ready; return path to sealed file."""
    from agentq_transport_client.ship import ship_file_drop

    # ship_file_drop expects manifest - for raw armored use write directly
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    sealed = out_dir / f"{stem}.agentq.asc"
    ready = out_dir / f"{stem}.agentq.ready"
    sealed.write_text(armored, encoding="utf-8")
    ready.write_text("", encoding="utf-8")
    return str(sealed)

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from .client_state import (
    ClientStateError,
    allocate_artifact,
    apply_git_exclude,
    plan_git_exclude,
    prepare_artifact_request,
    resolve_state_location,
    verify_artifact,
)


MAX_CONTENT_BYTES = 16 * 1024 * 1024


def _location(args, root: Path, home: Path):
    return resolve_state_location(
        root,
        args.client,
        cwd=Path(args.directory),
        home=home,
        scope=args.scope,
    )


def _content(path_value: str | None) -> bytes:
    if path_value is None:
        return b""
    path = Path(path_value).expanduser()
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise ClientStateError("content-file is unreadable", code="invalid_content") from exc
    try:
        details = os.fstat(fd)
        if not stat.S_ISREG(details.st_mode) or details.st_size > MAX_CONTENT_BYTES:
            raise ClientStateError("content-file must be a supported regular file", code="invalid_content")
        chunks: list[bytes] = []
        total = 0
        while chunk := os.read(fd, 1024 * 1024):
            total += len(chunk)
            if total > MAX_CONTENT_BYTES:
                raise ClientStateError("content-file exceeds the supported size limit", code="invalid_content")
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _print(payload: dict) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def handle(args, root: Path, home: Path) -> int | None:
    if args.cmd != "state":
        return None
    try:
        location = _location(args, root, home)
        if args.state_action == "path":
            plan = plan_git_exclude(location)
            if args.apply_exclude:
                plan = apply_git_exclude(plan)
            payload = location.payload()
            payload["exclude"] = plan.payload()
        elif args.state_action == "allocate":
            prepared = prepare_artifact_request(
                location,
                content=_content(args.content_file),
                purpose=args.purpose,
                extension=args.extension,
                kind=args.kind,
                schema=args.schema,
                producer=args.producer,
                agent=args.agent,
                predecessor=args.predecessor,
                checkpoint=args.checkpoint,
                consumers=args.consumer,
                metadata_schema=root / "ls" / "config" / "client-state-artifact.schema.json",
            )
            exclude = apply_git_exclude(plan_git_exclude(location))
            payload = allocate_artifact(location, prepared=prepared)
            payload["exclude"] = exclude.payload()
            payload["ok"] = True
            payload["scope"] = location.scope
            payload["state_path"] = location.state_path
        else:
            payload = verify_artifact(
                location,
                args.artifact,
                schema_path=root / "ls" / "config" / "client-state-artifact.schema.json",
            )
        _print(payload)
        return 0 if payload["ok"] else 1
    except ClientStateError as exc:
        _print({"error": {"code": exc.code, "message": str(exc)}, "ok": False})
        return 2
    except Exception:
        _print(
            {
                "error": {
                    "code": "client_state_internal_error",
                    "message": "client-state operation failed",
                },
                "ok": False,
            }
        )
        return 2

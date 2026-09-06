"""Private immutable policy and append-only heartbeat accounting receipts."""
import hashlib
import json
import os
from pathlib import Path

from . import heartbeat_budget as budget
from . import heartbeat_authorization as authority
from . import registration_owner as files
from .profile_setup import _absent, _parent, _target
from .runtime_lock import LOCK_NAME, runtime_use
from .session_owner import _separate

POLICY = "policy.json"


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _document(value, workspace):
    budget._keys(value, {"schema_version", "workspace", "policy", "authorizations"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["workspace"] != str(workspace):
        raise ValueError("Heartbeat policy workspace/schema mismatch")
    budget.validate_policy(value["policy"])
    authorizations = value["authorizations"]
    if not isinstance(authorizations, dict) or not 1 <= len(authorizations) <= 256:
        raise ValueError("Heartbeat authorization inventory exceeds bounds")
    for operation, authorization in authorizations.items():
        authority.validate(operation, authorization)
    return value


def _paths(root, workspace):
    root, workspace = _target(root), _target(workspace)
    _separate(root, workspace)
    return root, workspace


def _parse(raw):
    if raw is None:
        raise FileNotFoundError("Heartbeat policy or receipt is missing")
    value = json.loads(raw)
    if files.encode(value) != raw:
        raise ValueError("Heartbeat records require canonical JSON")
    return value


def _names(fd):
    names = set()
    with os.scandir(fd) as entries:
        for entry in entries:
            if len(names) >= 3074:
                raise ValueError("Heartbeat record inventory exceeds bounds")
            names.add(entry.name)
    return names


def _load(fd, workspace):
    names = _names(fd)
    raw = files._read(fd, POLICY)
    document = _document(_parse(raw), workspace)
    head = _hash(raw)
    names -= {POLICY, LOCK_NAME}
    expected = [f"{index:08d}.json" for index in range(len(names))]
    if names != set(expected):
        raise ValueError("Unexpected or incomplete heartbeat record inventory")
    records = []
    for name in expected:
        raw = files._read(fd, name)
        record = _parse(raw)
        budget._keys(record, {"previous", "event"})
        if record["previous"] != head:
            raise ValueError("Heartbeat accounting hash chain mismatch")
        event = record["event"]
        records.append(event)
        head = _hash(raw)
    _, summary = authority.replay(document, records)
    return document, records, head, summary


def initialize(root: Path, workspace: Path, document: dict, expected_sha256: str) -> dict:
    root, workspace = _paths(root, workspace)
    raw = files.encode(_document(document, workspace))
    if _hash(raw) != expected_sha256:
        raise ValueError("Heartbeat policy changed since review")
    fd = _parent(root / POLICY, create=True)
    try:
        with runtime_use(root, exclusive=True, timeout=5):
            if _names(fd) - {LOCK_NAME}:
                raise FileExistsError("Heartbeat accounting directory is not empty")
            _absent(fd, POLICY)
            files._publish(fd, POLICY, raw, 0o600)
    finally:
        os.close(fd)
    return inspect(root, workspace)


def inspect(root: Path, workspace: Path) -> dict:
    root, workspace = _paths(root, workspace)
    fd = _parent(root / POLICY, create=False)
    if fd is None:
        raise FileNotFoundError("Heartbeat accounting directory is missing")
    try:
        with runtime_use(root, timeout=5, create=False):
            document, records, head, summary = _load(fd, workspace)
            return {"head": head, "policy": document["policy"], "summary": summary,
                    "record_count": len(records)}
    finally:
        os.close(fd)


def append(root: Path, workspace: Path, event: dict, expected_head: str, *, binding: str | None = None) -> dict:
    root, workspace = _paths(root, workspace)
    fd = _parent(root / POLICY, create=False)
    if fd is None:
        raise FileNotFoundError("Heartbeat accounting directory is missing")
    try:
        if files._read(fd, LOCK_NAME) is None:
            raise FileNotFoundError("Heartbeat accounting lease is missing")
        with runtime_use(root, exclusive=True, timeout=5):
            document, records, head, _ = _load(fd, workspace)
            if head != expected_head:
                raise ValueError("Heartbeat accounting changed; inspect before retrying")
            if isinstance(event, dict) and event.get("type") == "reserve":
                grants, _ = authority.replay(document, records)
                authorization = grants.get(event.get("operation"))
                if authorization is None or authorization["binding"] != binding:
                    raise ValueError("Heartbeat action does not match controller authorization")
                if event != {"type": "reserve", "operation": event["operation"],
                             "run": authorization["run"], "compact": authorization["compact"]}:
                    raise ValueError("Heartbeat allocation does not match authorization")
            elif binding is not None:
                raise ValueError("Only a reservation supplies an action binding")
            _, summary = authority.replay(document, [*records, event])
            raw = files.encode({"previous": head, "event": event})
            files._publish(fd, f"{len(records):08d}.json", raw, 0o600)
            return {"head": _hash(raw), "policy": document["policy"], "summary": summary,
                    "record_count": len(records)+1}
    finally:
        os.close(fd)

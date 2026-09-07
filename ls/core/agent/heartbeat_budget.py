"""Conservative heartbeat reservations and controller disposition transitions."""
from copy import deepcopy

from .operation_journal import DIGEST, IDENTIFIER

DIMENSIONS = {"attempts", "requests", "tools", "tokens", "seconds", "compactions"}
CAPS = {"attempts": 1024, "requests": 65536, "tools": 262144,
        "tokens": 1073741824, "seconds": 31536000, "compactions": 1024}


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError("Invalid heartbeat accounting fields")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Heartbeat accounting requires bounded integers")


def _identity(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("Invalid heartbeat accounting identity")


def validate_policy(policy):
    _keys(policy, {"schema_version", "task", "revision", "criterion", "budget", "no_progress_limit"})
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 1:
        raise ValueError("Unsupported heartbeat accounting schema")
    _identity(policy["task"], IDENTIFIER)
    for name in ("revision", "criterion"):
        _identity(policy[name], DIGEST)
    _keys(policy["budget"], DIMENSIONS)
    for name, high in CAPS.items():
        _integer(policy["budget"][name], 0 if name in ("tools", "compactions") else 1, high)
    _integer(policy["no_progress_limit"], 1, policy["budget"]["attempts"])


def envelope(run, compact=None):
    """Charge full limits even if a phase fails or uses less than allocated."""
    _keys(run, {"requests", "tools", "tokens", "seconds"})
    for name, low, high in (("requests", 1, 64), ("tools", 0, 256),
                            ("tokens", 1, 1048576), ("seconds", 1, 86400)):
        _integer(run[name], low, high)
    result = {**run, "attempts": 1, "compactions": 0}
    if compact is not None:
        _keys(compact, {"tokens", "seconds"})
        _integer(compact["tokens"], 1, 1048576)
        _integer(compact["seconds"], 1, 86400)
        result["requests"] += 1
        result["tokens"] += compact["tokens"]
        result["seconds"] += compact["seconds"]
        result["compactions"] = 1
    return result


def summarize(policy, records):
    """Replay protected records; callers own durable storage and authorization."""
    validate_policy(policy)
    if not isinstance(records, list) or len(records) > 3072:
        raise ValueError("Heartbeat accounting record limit")
    charged = {name: 0 for name in DIMENSIONS}
    operations = set()
    pending = None
    consecutive = 0
    accepted = False
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Invalid heartbeat accounting record")
        kind = record.get("type")
        if kind == "reserve":
            _keys(record, {"type", "operation", "run", "compact"})
            _identity(record["operation"], IDENTIFIER)
            if pending is not None or accepted or consecutive >= policy["no_progress_limit"]:
                raise ValueError("Heartbeat task requires review or has stopped")
            if record["operation"] in operations:
                raise ValueError("Heartbeat operation cannot be replayed")
            allocation = envelope(record["run"], record["compact"])
            if any(charged[name] + allocation[name] > policy["budget"][name] for name in DIMENSIONS):
                raise ValueError("Heartbeat task budget exhausted")
            charged = {name: charged[name] + allocation[name] for name in DIMENSIONS}
            operations.add(record["operation"])
            pending = {"operation": record["operation"], "result": None}
        elif kind == "result":
            _keys(record, {"type", "operation", "result"})
            _identity(record["result"], DIGEST)
            if pending is None or pending["operation"] != record["operation"] or pending["result"] is not None:
                raise ValueError("Heartbeat result has no unresolved reservation")
            pending["result"] = record["result"]
        elif kind == "review":
            _keys(record, {"type", "operation", "result", "decision", "evidence", "rationale"})
            if (pending is None or pending["result"] is None or
                    (record["operation"], record["result"]) != (pending["operation"], pending["result"])):
                raise ValueError("Controller review must bind the recorded result")
            if record["decision"] not in ("progress", "no_progress", "accepted"):
                raise ValueError("Invalid controller progress disposition")
            _identity(record["evidence"], DIGEST)
            if not isinstance(record["rationale"], str) or not record["rationale"].strip() or len(record["rationale"]) > 2048:
                raise ValueError("Controller review requires a bounded rationale")
            consecutive = consecutive + 1 if record["decision"] == "no_progress" else 0
            accepted = record["decision"] == "accepted"
            pending = None
        else:
            raise ValueError("Unsupported heartbeat accounting event")
    status = ("accepted" if accepted else "no_progress_stop" if consecutive >= policy["no_progress_limit"]
              else "reconciliation_required" if pending and pending["result"] is None
              else "awaiting_controller_review" if pending else "ready")
    return {"status": status, "charged": charged,
            "remaining": {name: policy["budget"][name] - charged[name] for name in DIMENSIONS},
            "consecutive_no_progress": consecutive, "pending": pending}


def append(policy, records, event):
    """Validate an immutable candidate before the storage owner persists it."""
    candidate = deepcopy(records)
    candidate.append(deepcopy(event))
    return candidate, summarize(policy, candidate)

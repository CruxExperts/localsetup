"""Replay additive controller grants without changing the task budget policy."""
import hashlib

from . import heartbeat_budget as budget
from .registration_owner import encode


def validate(operation, authorization):
    budget._identity(operation, budget.IDENTIFIER)
    budget._keys(authorization, {"binding", "run", "compact"})
    budget._identity(authorization["binding"], budget.DIGEST)
    budget.envelope(authorization["run"], authorization["compact"])


def replay(document, records):
    if not isinstance(records, list) or len(records) > 3072:
        raise ValueError("Heartbeat accounting record limit")
    policy_digest = hashlib.sha256(encode(document)).hexdigest()
    grants = dict(document["authorizations"])
    accounting = []
    for event in records:
        if isinstance(event, dict) and event.get("type") == "authorize":
            budget._keys(event, {"type", "operation", "authorization", "policy_sha256"})
            validate(event["operation"], event["authorization"])
            if event["policy_sha256"] != policy_digest:
                raise ValueError("Heartbeat authorization policy mismatch")
            if event["operation"] in grants or len(grants) >= 256:
                raise ValueError("Heartbeat authorization already exists or inventory is full")
            if budget.summarize(document["policy"], accounting)["status"] != "ready":
                raise ValueError("Heartbeat task requires review or has stopped")
            grants[event["operation"]] = event["authorization"]
        else:
            if isinstance(event, dict) and event.get("type") == "reserve":
                authorization = grants.get(event.get("operation"))
                if authorization is None or event != {"type": "reserve", "operation": event["operation"],
                        "run": authorization["run"], "compact": authorization["compact"]}:
                    raise ValueError("Heartbeat reservation differs from authorization")
            accounting.append(event)
    return grants, budget.summarize(document["policy"], accounting)

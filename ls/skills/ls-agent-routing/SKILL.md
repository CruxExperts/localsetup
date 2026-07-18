---
name: ls-agent-routing
description: Select a reviewed LocalSetup Agent-* lane from a bundled static capability matrix without probing accounts or networks.
metadata:
  version: "1.0"
---

# LocalSetup Agent Routing

Use this skill when a bounded task needs a deterministic, reviewed `Agent-*`
lane recommendation. The selector reads only its bundled matrix and writes a
share-safe JSON receipt. It does not select a client model, effort, permission,
or worker configuration.

## Select a lane

Provide a closed JSON request on standard input or in a file:

```bash
python3 scripts/agent_routing.py select --request request.json
```

```bash
printf '%s' '{"schema":"agent_routing_request_v1","task_class":"routine","risk":"low","required_capabilities":[]}' \
  | python3 scripts/agent_routing.py select --request -
```

Treat `rejected` and `offline` receipts as typed results. Do not add a model,
price, account, observation, permission, or Ultra override to the request.

## Boundaries

- The matrix is static reviewed evidence. Unknown capability evidence never
  satisfies a request.
- `Agent-*` is a LocalSetup routing-policy label, not a provider model claim.
- The selector is read-only and does not inspect runtime availability or
  observations.

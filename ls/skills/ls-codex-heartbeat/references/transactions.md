---
status: ACTIVE
version: 3.4
---

# Transactions

The heartbeat harness uses a file transaction:

1. Acquire `heartbeat.lock`, or return current owner evidence without touching state.
2. Recover abandoned staged runs only while holding the lock.
3. Create `runs/<run-id>.staged`.
4. Write `active.json`.
5. Run hooks and the optional configured agent command.
6. Write the result, command log, sidecars, and manifest hashes.
7. Validate the staged artifact graph.
8. Atomically promote to `runs/<run-id>`, update `latest.json`, and remove `active.json`.

If validation fails, the staged run is not promoted as successful. Future lock-owning runs preserve abandoned staged work as recovered failure evidence.

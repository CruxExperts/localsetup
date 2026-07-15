---
status: ACTIVE
version: 3.4
---

# Transactions

The heartbeat harness uses a simple file transaction:

1. Acquire `heartbeat.lock`.
2. Create `runs/<run-id>.staged`.
3. Write `active.json`.
4. Run hooks and optional Codex command.
5. Write result artifacts and hashes.
6. Validate staged artifacts.
7. Atomically promote to `runs/<run-id>`.
8. Replace `latest.json` and remove `active.json`.

If validation fails, the staged run is not promoted as successful. Future runs preserve abandoned staged work as recovered failure evidence.

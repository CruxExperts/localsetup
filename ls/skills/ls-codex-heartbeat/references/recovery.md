---
status: ACTIVE
version: 3.4
---

# Heartbeat Recovery

A fresh run acquires `heartbeat.lock` before it scans `*.staged` directories or reads `active.json`. Any staged run left after a prior owner is finalized as `failed_recovered`, preserved under a `*.recovered-*` directory, and recorded in the next run manifest.

An existing lock stays authoritative unless all of these hold: its JSON has a creation time, same-host name, and positive PID; the recorded age meets `heartbeat.stale_after_seconds`; and the same-host PID no longer exists. Only then does the harness acquire the old inode lock, unlink that held stale pathname, close the old descriptor, and retry exclusive creation. It never renames a locked inode. Cross-host, malformed, unreadable, permission-denied, future-dated, young, or live-PID locks return `status: locked` without changing state.

## Ambiguous lock procedure

1. Run `localsetup harness codex-heartbeat status` and preserve the reported lock evidence.
2. Confirm with the lock owner or host operator that no heartbeat process owns the recorded PID. Age alone is not sufficient.
3. Do not delete or rename the lock manually. The runtime reclaims only a proven stale lock while it holds that inode; any ambiguous lock remains a stop condition.
4. If ownership cannot be established, leave the lock in place and investigate.

Corrupt or unsafe pointers also stop the run instead of being silently trusted.

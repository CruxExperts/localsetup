---
status: ACTIVE
version: 3.4
---

# Heartbeat Recovery

Before a fresh run starts, the harness scans for interrupted `*.staged` runs. Any staged run left behind is finalized as `failed_recovered`, preserved under a `*.recovered-*` directory, and recorded in the next run's manifest.

Corrupt or unsafe pointers stop the run instead of being silently trusted. Lock-held runs report `status: locked` and leave the current owner evidence in place.

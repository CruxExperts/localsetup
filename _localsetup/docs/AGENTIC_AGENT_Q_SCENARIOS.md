---
status: ACTIVE
version: 3.0
audience: humans, agents
---

# Agent Q scenarios: repos, agents, local, remote

**Purpose:** Describe how **file_drop** (and when relevant **mail**) works across common deployments: same machine vs remote, same repo vs different repos, and how agents A/B align on paths and keys. Written for operators and for agents that must choose commands without guessing. **This document and [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md) define transport and registry behavior; queue layout and batch processing live in [AGENTIC_AGENT_Q_PATTERN.md](AGENTIC_AGENT_Q_PATTERN.md).**

**Prerequisites:** [AGENTIC_AGENT_TO_AGENT_PROTOCOL.md](AGENTIC_AGENT_TO_AGENT_PROTOCOL.md), [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md). Client CLI: `_localsetup/tools/agentq_transport_client/agentq_cli.py`.

---

## 1. Concepts (minimal)

| Concept | Meaning |
|--------|--------|
| **Agent** | Logical identity (`agent-a`, `agent-b`) with OpenPGP keys and registry entry. Not the same as "Cursor session" or "repo clone". |
| **Queue** | Per-deployment filesystem tree (`in/`, `inbox/`, ledger). Usually under `.agent/queue` in that repo. **Not shared** between repos unless you point both at the same `queue_path`. |
| **file_drop root** | Shared **directory**. Writer drops sealed blob + ready marker; reader polls or ingests from that directory. **Must be the same absolute path** (or equivalent) on both sides when on the same machine. |
| **Sealed blob** | One armored OpenPGP message (encrypt-only or strict gpg). Recipient **private key** decrypts; optional strict path verifies signer fingerprint vs registry. |
| **Registry** | `agent_trust_registry.yaml`: who is allowed, where their **public** keys live, which **file_drop roots** each agent may read or write. |

**Invariant:** Transport moves **bytes** only. **Validation** (registry, decrypt, manifest) is the same no matter if the folder is local, NFS, or sync-cloned.

---

## 2. Scenario matrix

| Scenario | Queue location | Drop folder | Typical transport | Notes |
|----------|----------------|-------------|-------------------|--------|
| A and B, **same machine**, **different repos** | Each repo has its own `.agent/queue` | **One shared path outside both repos** (e.g. `~/agentq-drop/to-b`) | file_drop | Both registry YAMLs reference the same absolute path for inbound/outbound. |
| A and B, **same machine**, **same repo** (e.g. worktrees) | Can share one queue or separate | Shared path or subdirs per direction | file_drop | Same as above if two agents still use distinct keys and registry entries. |
| A **local**, B **remote** | Each side its own queue | Sync folder (Dropbox/Drive/rsync) or **mail** | file_drop or mail | file_drop needs a folder both can see (sync or mount). If no shared FS, use mail. |
| A and B, **both remote**, no shared FS | Each queue local to that host | N/A for file_drop without sync | **mail** (or sync + file_drop) | file_drop requires a **common filesystem namespace** at some layer. |
| CI / headless B | B's queue on runner | Artifact upload dir or mail | file_drop to artifact dir or mail | B runs `ingest-blob` or `file-drop-poll` in CI with ephemeral key from secret store. |

---

## 3. Same machine, different repos (detailed)

**Goal:** Repo1 (agent A) ships a PRD to repo2 (agent B) without committing secrets.

**Setup:**

1. **Create a drop directory** not inside either repo, e.g. `/home/you/agentq/to-b` or `~/agentq/to-b`.
2. **Keys:** A holds B's **public** key file; B holds **private** key file. Paths in registry are **public key paths only**.
3. **Registry on A's side:** Under `agents.agent-b.file_drop.allowed_outbound_roots` (or document that A writes only under paths B lists as inbound), include `~/agentq/to-b` expanded to absolute path.
4. **Registry on B's side:** `agents.agent-a` with A's public key; `file_drop.allowed_inbound_roots` includes the **same** absolute path.

**A ships (from repo1):**

```bash
cd /path/to/repo1
python _localsetup/tools/agentq_transport_client/agentq_cli.py ship-file-drop \
  --manifest path/to/spec.prd.md \
  --pubkey /secure/keys/agent-b.pub.asc \
  --out /home/you/agentq/to-b \
  --stem handoff-20250310 \
  --queue .agent/queue
```

Optional strict gpg:

```bash
# A also passes --signer-gnupghome and --signer-uid; B ingests with --strict-gpg --registry ...
```

**B ingests (from repo2):**

One-shot:

```bash
cd /path/to/repo2
python _localsetup/tools/agentq_transport_client/agentq_cli.py ingest-blob \
  /home/you/agentq/to-b/handoff-20250310.agentq.asc \
  --queue .agent/queue \
  --privkey /secure/keys/agent-b.sec.asc \
  --registry _localsetup/config/agent_trust_registry.yaml
```

Or poll (cron/systemd) scanning B's inbound roots from registry:

```bash
python _localsetup/tools/agentq_transport_client/agentq_cli.py file-drop-poll \
  --queue .agent/queue \
  --privkey /secure/keys/agent-b.sec.asc \
  --registry path/to/registry.yaml \
  --agent agent-a
```

**What happens:** B's queue gains `in/<id>/` with PRD and optional attachments; A's blob moves under `processed/` under the drop dir. Ledger on **B's** queue records idempotency. A's repo is unchanged except ship_log if `--queue` was set.

**Common mistakes:**

- Using a **repo-relative** path on A that resolves differently on B (e.g. `./drop`): use **absolute** paths in registry.
- Forgetting **ready marker**: ship-file-drop writes `.ready` after `.asc`; ingest ignores incomplete pairs.
- B using **A's** privkey: decrypt will fail; sealed blob is for B's pubkey only.

---

## 4. Same machine, same repo (two agents)

If both agents are **roles** in the same clone (e.g. human + automated builder), you can:

- Use **two subdirs** under one drop base: `.../to-builder/`, `.../to-human/`.
- Or one queue with **flat** layout and manual `in/` drops (no adapter).

Registry still lists two `agents.*` entries with distinct key paths and roots. Ship direction is determined by whose pubkey you pass to `ship-file-drop` and who runs `ingest-blob`.

---

## 5. Local vs remote (no shared directory)

**file_drop** requires the sealed file to **exist on disk** where B can read it. If B is on another host with no mount/sync:

- Use **mail:** `ship-mail` or `ship-mail-strict` from A; B runs `mail-pull` with B's account and policy.
- Or use a **sync folder** (Drive/Dropbox client) so both hosts see the same path eventually; then file_drop poll on B.

**Latency:** file_drop over sync is eventually consistent; ready marker + optional `sha256` first line in `.ready` reduces truncated-ingest risk.

---

## 6. Remote B with sync (step-by-step)

1. A and B agree on a **sync-relative** path that maps to the same logical folder on both machines after sync (e.g. `~/Dropbox/agentq/incoming`).
2. A `ship-file-drop --out ~/Dropbox/agentq/incoming`.
3. After sync completes, B runs `file-drop-poll` with `--root ~/Dropbox/agentq/incoming` (or registry inbound roots pointing there).
4. If sync creates conflict copies, **ignore_globs** in queue config should include `*conflicted copy*`.

---

## 7. Mail-only path (reference)

When file_drop is not available:

- A: `ship-mail` or `ship-mail-strict` (strict needs signer GNUPGHOME + recipient pubkey file).
- B: `mail-pull --queue .agent/queue --account ... --registry ...`
- Post-ingest move to Processed avoids UNSEEN replay; use `mail-move-retry` if policy blocked the first move.

See client **ADMIN_GUIDE** and mail skill for policy tokens.

---

## 8. Decision guide for agents

Use this flow to pick transport:

1. **Can B read the same directory as A writes?** (same host path, NFS, or sync)  
   - Yes → **file_drop**: `ship-file-drop` + `ingest-blob` or `file-drop-poll`.  
   - No → **mail** (or add sync first).

2. **Must outer blob be gpg sign-then-encrypt?**  
   - Yes → A: `--signer-gnupghome` on ship-file-drop; B: `--strict-gpg` on ingest; or `ship-mail-strict` + B mail-pull with decrypt compatible with inner JSON.

3. **Multiple recipients?**  
   - Manifest `to_agent_ids` + `ship-file-drop-multi` + registry pubkeys per id.

4. **Ack workflow?**  
   - Manifest `ack_required`; use `queue-pending` to move `in/*` to `pending/` after promote.

---

## 9. File reference map

| Need | Doc or path |
|------|----------------|
| Registry shape | `_localsetup/config/agent_trust_registry.example.yaml` |
| Queue config | `_localsetup/config/agent_queue.example.yaml` |
| CLI commands | `_localsetup/tools/agentq_transport_client/docs/USER_GUIDE.md` |
| Admin / policy | `_localsetup/tools/agentq_transport_client/docs/ADMIN_GUIDE.md` |
| Protocol | `_localsetup/docs/AGENTIC_AGENT_TO_AGENT_PROTOCOL.md` |
| Build order | `_localsetup/docs/AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md` |

---

## 10. Glossary

| Term | Definition |
|------|------------|
| **Stem** | Base filename for `stem.agentq.asc` and `stem.agentq.ready`. |
| **Promote** | Atomic move from staging to `in/<transport_id>/`. |
| **Ledger** | Append-only JSONL idempotency log under queue `inbox/` and `out/`. |
| **Strict gpg** | Outer blob is gpg sign+encrypt of raw JSON manifest; ingest verifies Good signature vs registry. |

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a>
</p>

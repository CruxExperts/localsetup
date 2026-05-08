---
status: ACTIVE
version: 3.0
---

# Agent-to-agent protocol (PRD + transport)

**Purpose:** How Agent A and Agent B exchange PRDs and artifacts over pluggable transports (mail, file_drop, future IM). Validation is **transport-independent**: **OpenPGP sign-then-encrypt** and a **YAML agent trust registry** gate what gets promoted to the queue.

**Build contract:** [AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md](AGENTIC_AGENT_Q_BIDIRECTIONAL_BUILD_SPEC.md) (v2.0) is the implementation order; core pipeline and file_drop ingest are implemented under `_localsetup/tools/agentq_transport_client/`. Mail adapter post-ingest move remains policy-gated via mail skill.

**Scenarios (repos, agents, local/remote):** [AGENTIC_AGENT_Q_SCENARIOS.md](AGENTIC_AGENT_Q_SCENARIOS.md).

## Principles

- **Everything on disk before batch:** Transport adapters write to inbox/staging; PRD batch stays filesystem-only.
- **Ack** only when `ack_required: true` on the request.
- **Delivery/deliverable** per request only (`delivery`, `deliverable` in PRD or inner manifest).
- **No plaintext adapter ingest:** Adapter pull path always verify then decrypt; manual PRD drop into flat `in/` remains valid without crypto.
- **Symmetric deploy:** Same framework and registry shape on both sides.

## Registry

- **agent_trust_registry.yaml** in-repo with **paths only** to OpenPGP public keys; private keys never in repo.
- Inbound: verify signature maps to agent_id; inner `from_agent_id` must match signer binding or reject.
- **Mail:** optional post-ingest move to `LocalsetupAgentQ/Processed` (mandatory when adapter implements mail path).
- **file_drop:** allowed_inbound_roots / allowed_outbound_roots only; sealed extension default `.agentq.asc`; ready marker sibling; writer order payload then ready last.

## Flows

**Inbound:** Adapter fetch -> verify OpenPGP -> decrypt -> validate inner manifest + checksums -> staging -> atomic promote to `in/` -> move source to processed -> ledger append.

**Outbound:** Pre-ship gate -> build manifest + checksums -> encrypt_then_sign -> mail or file_drop push -> archive sidecar.

**Iteration:** Stable `conversation_id`; optional `iteration`; B retains archive under `.agent/queue/archive/<conversation_id>/` for unfold-debug; attach-back or archive-unfold when A reports live issues.

## Pre-ship gate (B)

Before ship: localsetup-skill-sandbox-tester where applicable; localsetup-debug-pro on failure; localsetup-test-runner if code PRD; or PRD `pre_ship_checks`; or `skip_pre_ship_checks` + reason in outcome.

## Framework version stamp

Tool-generated PRDs must set `localsetup_framework_version` from repo VERSION; optional hash. Ingest may warn/block on mismatch per config.

## Edge cases

- Framework version mismatch: warn/block per policy.
- B archive missing: B requests attach-back.
- Attach-back over limit: manual handoff or links.
- Iteration without conversation_id: reject or new thread + warn.
- Pre-ship fails: no ship without skip + reason.

## Implemented commands (client CLI)

- **ship-file-drop** – Seal manifest with recipient pubkey; write `stem.agentq.asc` then `stem.agentq.ready`.
- **ingest-blob** – Decrypt armored file; promote to `in/<id>/`.
- **mail-pull** – Policy-gated UNSEEN fetch, decrypt, promote, move to `LocalsetupAgentQ/Processed` (or `--post-mailbox`).
- **ship-mail** – `mail_send_encrypted` with `agentq_outer` envelope; requires recipient pubkey in account crypto env.

## Documentation

USER_GUIDE and ADMIN_GUIDE beside client package; cross-links from mail-protocol-control and AGENTIC_AGENT_Q_PATTERN.

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a>
</p>

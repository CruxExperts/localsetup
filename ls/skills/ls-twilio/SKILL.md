---
name: ls-twilio
description: Inventory wrapper for Twilio AI skills and MCP surfaces. Use when planning
  Twilio messaging, voice, Verify, SendGrid, or communications integrations.
metadata:
  version: '1.0'
extensions:
  external_skill:
    source_kind: wrapper
    source_url: https://github.com/twilio/ai
    source_path: <repository inventory>
    source_commit: aa67a6d476107d6742f31a53d68b10749552930f
    source_ref: main
    source_sha256: 1bdb513e484c15fafbc8f9d3187d5c239a4c7d2afe4faf72c7fcb45bbcdffb07
    license: MIT
    import_date: '2026-07-03'
    vetting_status: provenance-recorded-no-bundled-tooling-executed
---

# Twilio Ai Skill And Mcp Bundle

Use this skill when working on Twilio AI skill and MCP bundle tasks.

## Workflow

- Check whether the task needs Twilio REST APIs, messaging/voice webhooks, SendGrid email, or MCP tooling.
- Protect account SIDs, auth tokens, API keys, phone numbers, message bodies, call recordings, and webhook secrets.
- Use test credentials or sandbox numbers where available before production sends or calls.

## Boundaries

- Inspect the target repository before making changes.
- Prefer existing project patterns, declared package managers, and documented validation commands.
- Do not expose secrets, credentials, private user data, or production account identifiers in source, examples, or logs.
- When external APIs or current vendor behavior matter, verify against official docs before implementation.


## Upstream Coverage

See [upstream coverage](./references/upstream-coverage.md) for the compact inventory captured during this import wave.

## Provenance

- Source: `https://github.com/twilio/ai`
- Ref: `main` at `aa67a6d476107d6742f31a53d68b10749552930f`
- Source path: `<repository inventory>`
- License classification: `MIT`
- Source SHA-256: `1bdb513e484c15fafbc8f9d3187d5c239a4c7d2afe4faf72c7fcb45bbcdffb07`

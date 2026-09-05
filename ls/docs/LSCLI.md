---
status: ACTIVE
version: 4.4
owner_skill: ls-architecture
---

# LSCli bootstrap and diagnostics

LSCli is the integrated CLI for LocalSetup (LS). Its command is `lscli`; the
existing framework command and Python distribution remain `localsetup`.
The current bootstrap provides help, version output, and read-only diagnostics.
Agent execution is not yet available. A verified SDK payload alone does not
establish protected runtime, sandbox, provider, or supervisor readiness.

```bash
lscli --help
lscli --version
lscli doctor
lscli doctor --format json
```

Help and version return 0. Doctor currently returns 3 because execution gates
remain unavailable; payload verification is reported independently. Calling
`lscli` without a subcommand returns 3 with diagnostic guidance on standard error.
Invalid arguments return argparse's status 2. Doctor text or JSON goes to standard
output. None of these commands loads provider/SDK modules, discovers credentials,
makes provider calls, or creates configuration or state directories.

The JSON diagnostic is versioned with `schema_version: 1`. It includes `product`,
`application`, `framework_version`, `status`, `sdk_payload`,
`execution_available`, `locations`, and `issues`. Payload status is `verified`,
`missing`, or `invalid`. Verification inspects the installed private payload's
manifest and files without importing them. Source/editable development has no
installed private payload and never falls back to the canonical vendor tree.
A missing or damaged payload calls for a verified framework wheel installation.
Diagnostic integrity evidence is not artifact authentication.

## State locations

The new CLI follows the existing global framework home under the user's home:

| Purpose | Path relative to the user home |
| --- | --- |
| Durable CLI state and future sessions | `.local/share/localsetup/state/lscli` |
| Explicit provider profile configuration | `.local/share/localsetup/config/lscli/profiles.json` |
| Managed release runtimes | `.local/share/localsetup/runtimes/lscli` |

Diagnostics only reports these locations. Profile creation, session persistence,
protected runtime installation, PATH collision handling, runtime-use locks, and
agent dispatch are subsequent implementation gates. Do not infer support for
those operations from the existence of an entry point or a reported path.
Existing framework state, adapter ownership, and stored heartbeat identifiers
are unchanged. See [SDK source and dependency maintenance](SDK_FORK.md) for the
private payload, dependency lock, build, and artifact boundaries.

## Candidate verification

A Python 3.12/Linux wheel installation was checked outside the source checkout.
Its installed `lscli` command returned help and version successfully; doctor
reported `sdk_payload: verified` and `execution_available: false` with exit 3.
The check used a nonexistent temporary user home and confirmed that no home or
state directories were created. A separate isolated Python invocation confirmed
the installed module origin and absence of SDK, provider, HTTP, and YAML imports.
This evidence qualifies the provider-free bootstrap only.

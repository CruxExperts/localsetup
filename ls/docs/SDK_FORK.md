---
status: ACTIVE
version: 4.4
owner_skill: ls-architecture
---

# LSCli SDK source ownership

LocalSetup owns one canonical SDK source tree at `vendor/lscli`. It retains the
upstream `pydantic_ai`, `pydantic_graph`, and `pydantic_ai_harness` namespaces and
MIT license texts. These are private implementation dependencies for LSCli.
Never add this tree to the supervisor's import path. Only the isolated SDK worker
may import it after the installed runtime's integrity and authority gates pass.

The source inventory is established; wheel payload generation, protected runtime
bootstrap, and agent execution are not yet available. Optional upstream modules
remain in the source for attribution and fork maintenance. Their presence does
not qualify providers, MCP, browser tools, subagents, or other integrations.

## Provenance and changes

`vendor/lscli/manifest.json` identifies each distribution, version, immutable
repository commit, source archive digest, license, namespace, and every retained
file. `upstream_sha256` records original runtime bytes; `sha256` records the local
bytes. Every changed runtime file has a retained patch. The initial patch makes
Slim's version lookup static so it does not require the original distribution's
installed metadata. It does not change the framework version or request identity.

The selected baselines are Pydantic AI Slim and Graph **2.38.0** and Pydantic AI
Harness **0.28.1**. Downloaded PyPI sdist digests and publish-attestation subjects
were cross-checked with immutable GitHub source: all 564 retained runtime files
matched before patching. The recorded verification uses HTTPS registry
attestations and source-byte comparison; it is not independent Sigstore
certificate-chain verification. Upstream tests, build tooling, and unrelated
repository documentation are not part of the runtime payload.

The dated dependency inventory covers the Slim OpenAI extra, base Graph/Harness,
and upstream plus LocalSetup build tools resolved for Python 3.12 on Linux.
OSV, GitHub Advisory Database, and deps.dev/PyPI returned no advisories for those
40 exact versions on 2026-09-05; none was yanked on PyPI. This inventory is evidence
for source adoption, not a supported-platform lock or a guarantee of safety.
Managed runtime locks, combined framework dependency compatibility, installed
imports, and ordinary wheel compatibility require separate executable evidence.

The documentation inventory identifies byte-identical retained manuals as
upstream documents with immutable source URLs. Their examples and links retain
the original repository context and are not LocalSetup operational guidance.
LocalSetup lifecycle, capability-count, and local-link rules apply to owned
documents; payload integrity and source ownership still apply to every retained
manual. New or modified files cannot acquire upstream status through a directory
name alone.

## Verify and refresh

Run the standard-library verifier without installing or importing the SDK:

```bash
uv run --locked python ls/tools/validate_sdk_payload.py --root vendor/lscli
```

It rejects missing, extra, modified, symlinked, special, and unsafe-path files,
invalid component ownership, missing licenses, and unrecorded local changes.
The manifest is an input to the release's trust boundary, not a signature. An
attacker who can replace both files and manifest can replace this evidence.
Run verification on a stable tree under the owning build/runtime lock; the
installed runtime must protect and authenticate its payload separately.

For a refresh:

1. Resolve the explicitly selected extras and complete runtime/build dependency
   closure. Audit exact versions against independent advisory sources before
   adoption; record platform markers, artifact hashes, and unresolved limitations.
2. Download exact source archives, verify registry digests and provenance, and
   compare retained runtime bytes to immutable upstream source. Never execute an
   archive to discover metadata or use unreviewed extraction paths or links.
3. Retain all namespace runtime resources and original MIT licenses. Reapply
   reviewed patches, recording original and resulting hashes and patch rationale.
4. Review the actual upstream and patch diff. Run payload, import-origin,
   packaging, installed-artifact, provider, and recovery checks for the affected
   behavior before accepting a new runtime. Refresh its SBOM and locked external
   dependencies through their owning build tools when those surfaces are present.
5. Commit accepted source changes and regenerate documentation through its owners
   in the required separate receipt. Keep machine evidence and private audit
   records outside public source and artifacts. Retain compatible prior release
   artifacts for recovery; never rewrite stored sessions during a source refresh.

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

Ordinary wheel builds verify the source and generate private SDK data under
`ls/_sdk_payload`. The build does not install upstream namespaces at the wheel
root or depend on installed upstream SDK distributions. Editable framework development remains available, but supplies no private SDK
payload and cannot qualify LSCli execution.
Protected runtime bootstrap and agent execution are not yet available. Optional upstream modules
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

## Wheel build boundary

The setuptools `BuildSDK` command owns the mapping from canonical source to wheel
data. It validates before copying, includes every listed runtime resource,
license, patch, and manifest, and verifies the resulting tree. Extra files,
symlinks, or a different retained manifest in a reused build directory stop the
build; use a fresh build output directory after changing the SDK source.

The build command loads its sibling verifier directly because setuptools loads
custom commands before the source package is importable. The core package also
resolves its `main` compatibility export lazily. The build helper imports only
the standard library and setuptools. No framework
runtime dependencies, provider credentials, or SDK imports are needed to build
the payload. Build from the source archive with the pinned setuptools backend;
source distributions retain the canonical vendor input through `MANIFEST.in`.
The installed worker's import-origin and runtime-protection checks are separate
requirements; a successful wheel build does not authorize agent execution.

Build and inspect candidates using the repository's pinned backend:

```bash
uv sync --locked --all-groups
uv run --locked pytest ls/tests/test_sdk_build.py ls/tests/test_sdk_payload.py -q
uv build --wheel --no-sources --out-dir dist
uv build --sdist --no-sources --out-dir dist
uv build --wheel dist/<source-distribution>.tar.gz --out-dir dist/from-sdist
```

Replace the source-distribution placeholder with the exact artifact just built.
The development group includes the same pinned setuptools version as the build
backend so the build-command regressions run in the normal project environment.
Python 3.12/Linux candidate checks established exact payload bytes for a source
wheel, sdist, and sdist-built wheel. A dependency-free installation also verified
the payload from outside the checkout without importing the SDK. These checks
qualify the packaging boundary; runtime external dependencies, supported provider
interfaces, protected worker execution, and other environments remain separate
qualification gates.

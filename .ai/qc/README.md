# GitHub QC Patrol

This directory defines the checked-in contract for repository-local QC patrols. Runtime output belongs in workflow artifacts under `qc-out/`; do not commit generated patrol state.

## Operating Posture

- Scheduled patrols may open or update duplicate-aware GitHub issues.
- PR checks surface as normal GitHub Actions checks plus step summaries and artifacts.
- Fork PRs run deterministic checks only and do not receive LLM secrets.
- Autofix is manual-only and limited to allowlisted deterministic repairs.
- LLM requests use bounded chunks, redacted inputs, and strict JSON response schemas.
- Adaptive patrol AI is opt-in. The default scheduled mode is deterministic packet generation only.

## Workflow Surface

- `qc-ci.yml` runs deterministic inventory, self-validation, and focused tests on PRs, pushes to `main`, merge queue, and manual dispatch.
- `qc-pr-review.yml` runs trusted base-branch tooling against a separate subject checkout. Same-repo PRs may use LLM secrets; fork PRs run without LLM secrets.
- `qc-patrol.yml` runs scheduled/manual repository patrols, writes adaptive inventory and drift artifacts, and may create or update duplicate-aware issues through a conservative policy gate.
- `qc-docs-drift.yml` runs scheduled/manual docs alignment handoff and may create or update duplicate-aware issues.
- `qc-release.yml` is manual release-readiness validation only. It builds and verifies temporary artifacts without publishing.
- `qc-autofix.yml` is manual-only and writes no code in v1; it only emits an autofix plan for explicit allowlist IDs.

## Adaptive Patrol Artifacts

`patrol` writes runtime artifacts under `qc-out/`:

- `inventory.json`: `qc.inventory.v2`, including tracked file hashes and classified docs, workflows, generated artifacts, packages, skills, workflow packages, private paths, registry/catalog metadata, and version truth.
- `drift-packets.json`: `qc.drift-packets.v1`, including deterministic shape drift and bounded markdown version-reference packets.
- `ai-adjudications.json`: `qc.ai-adjudication.v1`, empty by default unless packet adjudication is enabled.
- `rule-suggestions.json`: `qc.rule-suggestions.v1`, candidate deterministic rules suggested by AI adjudication. Rules are never auto-implemented.
- `ledger.json`: `qc.ledger.v2`, including inventory/drift summaries, deterministic findings, AI findings, rule suggestions, issue results, artifacts, and AI mode.

The scheduled workflow attempts to download the previous successful `qc-patrol-*` artifact and uses its `inventory.json` as the baseline. If no baseline can be loaded, patrol still runs and records a low-severity `shape.no_baseline` packet.

## AI Mode

`patrol --ai-mode off` is the default. It writes deterministic artifacts only.

`patrol --ai-mode packets` sends only individual packet payloads to the configured LLM. The prompt contract is `.ai/qc/prompts/patrol.md`, and each response must match `.ai/qc/schemas/ai-adjudication.schema.json`. The wrapper artifact written to `qc-out/ai-adjudications.json` matches `.ai/qc/schemas/ai-adjudications.schema.json`.

AI adjudication cannot mutate files, create pull requests, or bypass the issue policy. Medium and low confidence AI findings remain artifacts unless a later deterministic process promotes them.

## Issue Policy

The adaptive `patrol` command uses conservative issue gating:

- deterministic high or critical findings may create or update issues
- AI findings may create issues only when high confidence, actionable, explicitly marked `should_create_issue`, and backed by deterministic packet evidence
- medium and low AI findings remain artifact-only

Other existing issue-writing commands keep the legacy duplicate-aware handoff behavior unless they explicitly opt into the conservative policy.

## Secrets And Vars

Secrets: `QC_LLM_BASE_URL`, `QC_LLM_API_KEY`, optional `QC_LLM_ORGANIZATION`, optional `QC_LLM_PROJECT`.

Variables or checked-in defaults: `QC_LLM_MODEL`, `QC_LLM_TEMPERATURE`, `QC_LLM_MAX_TOKENS`, `QC_LLM_TIMEOUT_SECONDS`, `QC_LLM_RETRY_COUNT`, `QC_LLM_API_STYLE`, `QC_LLM_ENDPOINT_ALIAS`, `QC_PATROL_AI_MODE`.

The endpoint URL and secret headers must not be written to issues. Issues may record only the non-secret endpoint alias.

## Repository Settings

- Enable GitHub Actions for the repository.
- Keep the default token posture restrictive; each QC workflow declares the job-level access it needs.
- Allow `issues: write` only for patrol workflows that create or update issue handoffs.
- Enable "Allow GitHub Actions to create and approve pull requests" only if a future autofix implementation actually creates PRs. The v1 `qc-autofix.yml` workflow remains manual-only and plan-only.
- Do not add `pull_request_target` to QC review workflows. Untrusted fork PRs must not receive LLM secrets or write credentials.

## Release Boundary

The QC workflows live in `.github`, which is otherwise part of the public LocalSetup artifact. Because the QC tooling lives at root `tools/qc_patrol/` and is not shipped with the framework package, the exact `qc-*.yml` workflow paths are listed in `ls/config/pack.yaml` under `public_private.private_paths`.

Runtime output belongs in `qc-out/` workflow artifacts. Do not commit local patrol ledgers, raw LLM responses, or generated runtime state.

## Protected completion compatibility

QC's `LLMClient.complete(...)` retains its string result, default review schema
and prompt redaction. It uses LocalSetup's protected completion worker and shared
provider transport. Provision a verified managed runtime before enabling QC model
work; the wrapper never installs one automatically. `QC_LLM_RUNTIME_ROOT` selects
an explicit root, otherwise the default LSCli runtime location is used. Missing
credentials fail before dispatch. Model failures raise sanitized errors without
provider bodies, endpoint URLs or credentials. Successful JSON is compactly
serialized; formatting is not preserved byte-for-byte.

Both API styles and base URLs that include the selected endpoint suffix remain
supported. Explicit organization/project values are retained in the final request
headers; ambient SDK settings are ignored. Optional `QC_LLM_REASONING_EFFORT` must
be listed in comma-separated `QC_LLM_REASONING_EFFORTS`. Optional temperature is
sent only with `QC_LLM_TEMPERATURE_SUPPORTED=true`; the legacy zero default is
omitted otherwise, while an unsupported nonzero value refuses. The schema-name
argument is retained. `QC_LLM_ALLOW_LOOPBACK_HTTP=true` is only for explicitly
selected literal loopback fixtures; other endpoints require HTTPS.

`QC_LLM_RETRY_COUNT` remains readable for existing configuration, but no value
enables retries: the accepted completion policy permits one attempt. Transport
uncertainty is not replayed. The configured timeout bounds the protected worker,
including validation. The wrapper creates no sessions, configurations or recurring
jobs and preserves the existing caller-owned redaction and error-artifact flow.

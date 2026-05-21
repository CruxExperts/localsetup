# GitHub QC Patrol

This directory defines the checked-in contract for repository-local QC patrols. Runtime output belongs in workflow artifacts under `qc-out/`; do not commit generated patrol state.

## Operating Posture

- Scheduled patrols may open or update duplicate-aware GitHub issues.
- PR checks surface as normal GitHub Actions checks plus step summaries and artifacts.
- Fork PRs run deterministic checks only and do not receive LLM secrets.
- Autofix is manual-only and limited to allowlisted deterministic repairs.
- LLM requests use bounded chunks, redacted inputs, and strict JSON response schemas.

## Workflow Surface

- `qc-ci.yml` runs deterministic inventory, self-validation, and focused tests on PRs, pushes to `main`, merge queue, and manual dispatch.
- `qc-pr-review.yml` runs trusted base-branch tooling against a separate subject checkout. Same-repo PRs may use LLM secrets; fork PRs run without LLM secrets.
- `qc-patrol.yml` runs scheduled/manual repository patrols and may create or update duplicate-aware issues.
- `qc-docs-drift.yml` runs scheduled/manual docs alignment handoff and may create or update duplicate-aware issues.
- `qc-release.yml` is manual release-readiness validation only. It builds and verifies temporary artifacts without publishing.
- `qc-autofix.yml` is manual-only and writes no code in v1; it only emits an autofix plan for explicit allowlist IDs.

## Secrets And Vars

Secrets: `QC_LLM_BASE_URL`, `QC_LLM_API_KEY`, optional `QC_LLM_ORGANIZATION`, optional `QC_LLM_PROJECT`.

Variables or checked-in defaults: `QC_LLM_MODEL`, `QC_LLM_TEMPERATURE`, `QC_LLM_MAX_TOKENS`, `QC_LLM_TIMEOUT_SECONDS`, `QC_LLM_RETRY_COUNT`, `QC_LLM_API_STYLE`, `QC_LLM_ENDPOINT_ALIAS`.

The endpoint URL and secret headers must not be written to issues. Issues may record only the non-secret endpoint alias.

## Repository Settings

- Enable GitHub Actions for the repository.
- Keep the default token posture restrictive; each QC workflow declares the job-level access it needs.
- Allow `issues: write` only for patrol workflows that create or update issue handoffs.
- Enable "Allow GitHub Actions to create and approve pull requests" only if a future autofix implementation actually creates PRs. The v1 `qc-autofix.yml` workflow remains manual-only and plan-only.
- Do not add `pull_request_target` to QC review workflows. Untrusted fork PRs must not receive LLM secrets or write credentials.

## Release Boundary

The QC workflows live in `.github`, which is otherwise part of the public Localsetup artifact. Because the QC tooling lives at root `tools/qc_patrol/` and is not shipped with the framework package, the exact `qc-*.yml` workflow paths are listed in `_localsetup/config/pack.yaml` under `public_private.private_paths`.

Runtime output belongs in `qc-out/` workflow artifacts. Do not commit local patrol ledgers, raw LLM responses, or generated runtime state.

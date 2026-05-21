# QC Redaction Policy

Before LLM calls, redact PEM blocks, token-like URLs, credential assignments, `.env` values, and credential-like environment dumps.

Do not log `QC_LLM_BASE_URL`, `QC_LLM_API_KEY`, `QC_LLM_ORGANIZATION`, or `QC_LLM_PROJECT`. Issue text may mention only `QC_LLM_ENDPOINT_ALIAS`.

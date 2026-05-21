# QC PR Review Prompt

Return strict JSON matching `llm-review.schema.json`.

Review only the supplied bounded chunks, deterministic findings, affected paths, and policy excerpts. Do not infer repository state that is not present in the input. Prefer no finding over a speculative finding.

Every finding must include category, severity, title, body, affected paths, region, check type, and remediation.

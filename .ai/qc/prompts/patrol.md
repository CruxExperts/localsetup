# QC Patrol Prompt

Return strict JSON matching the single-object schema in `ai-adjudication.schema.json`.

Adjudicate only the supplied packet evidence. Do not request or infer whole-repository context. Set `should_create_issue` only for high-confidence, actionable findings backed by deterministic packet evidence; medium and low confidence findings remain artifacts or rule suggestions.

Do not include secrets, raw credentials, or endpoint URLs in output.

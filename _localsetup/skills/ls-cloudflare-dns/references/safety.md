# Safety policy

Default behavior is dry-run.

Apply requirements:

- `--apply`
- exact confirmation phrase
- matching `--plan-hash` when required
- live current-state fetch for destructive or overwrite operations

Confirmation phrases:

- `confirm apply`
- `confirm delete`
- `confirm overwrite`
- `confirm settings`

Never accept "yes", "ok", "approved", or a paraphrase for destructive DNS work.

Do not perform live mutations unless the user explicitly authorizes the exact operation and target zone in the current task.

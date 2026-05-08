# Admin guide

## Control model

The skill uses a profile-based policy model with action-level controls:

- `default_profile`
- per-account profile selection
- `allow_actions`
- `deny_actions`
- threshold settings for confirmation gates

## Attachment and crypto controls

- Enforce max attachment count, max single size, and max aggregate size.
- Use policy constraints to limit allowed encryption modes per profile or account.
- Restrict `imap.fetch_attachment_content` where data egress needs tighter guardrails.

## Policy resolution example

Given action `imap.delete_messages` for account `support`, resolution runs in this order:

1. `default_profile` rules
2. `accounts.support` overrides
3. per-request temporary constraints
4. final deny-overrides-allow check
5. threshold check for confirmation requirement

## Policy file

Path: `_localsetup/config/mail_protocol_policy.yaml`

Minimum structure:

```yaml
version: 1
default_profile: restricted
profiles:
  restricted:
    allow_actions:
      - smtp.*
      - imap.read.*
      - imap.write.*
    deny_actions:
      - imap.delete_mailbox
    thresholds:
      delete_count_confirm: 50
      move_count_confirm: 100
      expunge_requires_confirm: true
      folder_delete_requires_confirm: true
accounts:
  support:
    profile: restricted
```

## Credential setup

Use account-scoped variables first, then shared fallback variables.

Example:

```bash
export MAIL_ACCOUNT_SUPPORT_USERNAME="help@example.com"
export MAIL_ACCOUNT_SUPPORT_PASSWORD="app-password"
export MAIL_SHARED_USERNAME="fallback@example.com"
export MAIL_SHARED_PASSWORD="fallback-password"
```

For encryption keys and passphrases, follow the key contract in `KEY_MANAGEMENT.md`.

## Safety controls

- High-impact destructive actions can require short-lived confirmation tokens.
- Logs keep operation metadata but redact secret and message payload material.
- A dry-run rollout mode is recommended before enabling broad account coverage.

## Rollout model

1. Start with one non-critical account.
2. Validate query and send flows.
3. Validate mutation and confirmation flows.
4. Expand to broader account groups.

## Rollback model

1. Disable feature flag.
2. Override policies to read-only profile.
3. Keep send or read actions available only where needed.


# Account config schema

## Account file location

`_localsetup/config/mail_accounts.json`

A checked-in sample lives at
[`references/examples/mail_accounts.sample.json`](examples/mail_accounts.sample.json).

## Required shape

The account file root is a JSON array. Each item defines one delegated mailbox account.

```json
[
  {
    "account_id": "support",
    "smtp_host": "smtp.example.com",
    "smtp_port": 587,
    "smtp_tls_mode": "starttls",
    "imap_host": "imap.example.com",
    "imap_port": 993,
    "imap_tls": true,
    "username_field": "username",
    "password_field": "password"
  }
]
```

## Fields

| Field | Type | Required | Default | Notes |
|---|---|---:|---|---|
| `account_id` | string | yes | none | Stable delegated account ID used as `acct` in tool calls |
| `smtp_host` | string | yes | none | SMTP hostname |
| `smtp_port` | integer | no | `587` | Must be between `1` and `65535` |
| `smtp_tls_mode` | string | no | `starttls` | Use `starttls`, `ssl`, or provider-specific plain mode only when policy permits |
| `imap_host` | string | yes | none | IMAP hostname |
| `imap_port` | integer | no | `993` | Must be between `1` and `65535` |
| `imap_tls` | boolean/string | no | `true` | Accepts JSON booleans or `true`/`false` style strings |
| `username_field` | string | no | `username` | Credential provider field name |
| `password_field` | string | no | `password` | Credential provider field name |

## Validation

- The root value must be an array.
- Every row must be an object.
- `account_id`, `smtp_host`, and `imap_host` are required.
- `account_id` values must be unique after sanitization.
- `smtp_port` and `imap_port` must be bounded integers.
- Invalid files fail startup with `ACCOUNT_CONFIG_*` error codes instead of generic bootstrap errors.

## Credential environment names

For the sample account above, the default environment credential provider reads:

```bash
export MAIL_ACCOUNT_SUPPORT_USERNAME="agent-support@example.com"
export MAIL_ACCOUNT_SUPPORT_PASSWORD="provider-password-or-app-token"
```

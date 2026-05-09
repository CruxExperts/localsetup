# Key management

## Credential source order

1. account-scoped variable
2. shared variable fallback

## Auth credentials

- `MAIL_ACCOUNT_<ACCOUNT>_USERNAME`
- `MAIL_ACCOUNT_<ACCOUNT>_PASSWORD`
- `MAIL_SHARED_USERNAME`
- `MAIL_SHARED_PASSWORD`

## Crypto key material

- PSK:
  - `MAIL_ACCOUNT_<ACCOUNT>_PSK`
  - `MAIL_SHARED_PSK`
- Password-derived secret:
  - `MAIL_ACCOUNT_<ACCOUNT>_PASSWORD_SECRET`
  - `MAIL_SHARED_PASSWORD_SECRET`
- OpenPGP:
  - `MAIL_ACCOUNT_<ACCOUNT>_OPENPGP_PUBLIC_KEY`
  - `MAIL_ACCOUNT_<ACCOUNT>_OPENPGP_PRIVATE_KEY`
  - `MAIL_ACCOUNT_<ACCOUNT>_OPENPGP_PASSPHRASE`
  - shared fallbacks with `MAIL_SHARED_...`

## Key references

Optional `key_ref` allows suffix-based lookups:

- `MAIL_ACCOUNT_SUPPORT_PSK_TEAM1`
- `MAIL_SHARED_PSK_TEAM1`

## Security notes

- Keep private keys and passphrases out of git.
- Rotate keys and secrets regularly.
- Use account-specific values first for least privilege.
- Keep plaintext attachment payloads out of logs.


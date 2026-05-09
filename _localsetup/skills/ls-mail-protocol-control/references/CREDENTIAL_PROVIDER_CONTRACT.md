# Credential provider contract

## Required interface

```python
def get_credential(account_id: str, field: str) -> str: ...
def get_auth_bundle(account_id: str) -> dict[str, str]: ...
def get_crypto_bundle(account_id: str, key_ref: str = "default") -> dict[str, str]: ...
```

## Resolution order

1. Account-scoped environment variables.
2. Shared environment variables.
3. Optional backend adapter, for example Vault.

## Error behavior

- Missing credential: `CREDENTIAL_NOT_FOUND`
- Auth failure: `AUTH_FAILED`
- Missing key material: `KEY_MATERIAL_NOT_FOUND`

## Crypto bundle keys

`get_crypto_bundle` can return any subset of:

- `psk`
- `password_secret`
- `openpgp_public_key`
- `openpgp_private_key`
- `openpgp_passphrase`

## Security notes

- Do not persist credentials to disk.
- Do not log secrets.
- Optional cache TTL must stay short, default is no cache.


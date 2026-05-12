# Vault Backends

## KeePassXC

KeePassXC CLI is the operational backend. The wrapper checks for the local binary and keeps calls in argv form with `shell=False`.

The safe write field set is limited to `UserName`, `Password`, `URL`, `Notes`, title, and path. Custom protected attribute writes are rejected with `unsupported_field` unless a future version verifies a safe local CLI capability.

## Fake

The fake backend is for tests and examples. It can persist placeholder values to a JSON file with `--fake-store`, but that file is not a real vault.

## PyKeePass

PyKeePass is a possible future backend. It is not a dependency in this implementation.

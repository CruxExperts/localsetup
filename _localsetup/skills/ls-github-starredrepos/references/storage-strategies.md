# Storage Strategies

| Mode | Use | Committed content |
|---|---|---|
| `metadata` | First dry runs, current helper apply mode, and lightweight docs | Manifest, snapshots, docs |
| `submodule` | Planned publishable mode after guarded submodule creation is implemented | Git submodule pointers under `modules/` |
| `checkout-cache` | Local inspection only | Nothing from the checkout cache |
| `bare-mirror-cache` | Local archival cache only | Nothing from the mirror cache |
| `vendor` | Rare, explicitly approved full copy | Repository contents after license/privacy/size review |

`vendor` must not be selected by default. Confirm the user understands license, privacy, repository size, generated files, and secret-leak risk.

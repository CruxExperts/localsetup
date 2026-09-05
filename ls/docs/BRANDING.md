---
status: ACTIVE
version: 4.4
owner_skill: ls-script-and-docs-quality
---

# Product naming and branding validation

Introduce the framework as **LocalSetup (LS)**. Use **LocalSetup** for product
display text and **LSCli** for the integrated CLI display name. Its command is
`lscli`. The existing framework command and Python distribution remain
`localsetup`; neither `LS` nor `ls` is a new command alias.

This contract changes display text, not compatibility identifiers. Preserve
existing imports, filenames, directories, URLs, environment variables, persisted
keys, package names and protocol values. Preserve upstream attribution and
immutable historical evidence. Update owned generator inputs before regenerating
their output. Managed policy text must be changed through its owning source and
generator, never by editing a rendered tail.

## Runtime identity

Installer help, wizard titles, core diagnostics, package descriptions and new
release titles use the canonical display spelling. The wizard uses a plain
`LocalSetup installer` title so its terminal banner has the same spelling.
Diagnostic prose may change case; command prefixes, JSON keys, error codes,
environment-variable names and recorded paths retain their existing contracts.
Automation should use those structured values instead of matching display prose.

The Agent Q processed-mailbox identifier and existing non-model skill-index and
skill-validation user-agent values are compatibility identifiers. Their retained
spelling does not define the model-request identity below.

`ls.core.branding` exports `PRODUCT_NAME`, `PRODUCT_ABBREVIATION`, `CLI_NAME` and
`CLI_COMMAND`. Its `user_agent()` constructs the exact model-request identity
`LocalSetup/<framework_version()>` through the existing runtime version resolver.
The helper has no SDK dependency. Calling the helper alone does not prove the
header reached a provider: transport integration must enforce it at final send,
and request-capture tests must verify actual bytes for coding, compaction and
direct completion.

## Inventory and report mode

Run from the source checkout:

```bash
uv run --locked python ls/tools/validate_branding.py --repo-root .
```

The JSON report inventories Git-tracked and nonignored new files, hashes regular
files, records visual assets, and classifies each product-name occurrence.
Symlinks are inventoried without reading their targets. Unreadable paths are
findings. Private ignored state is outside this public repository scan; review
current private operational guidance separately without publishing it.

Classification is conservative: canonical display names and recognizable
technical tokens pass automatically. Ambiguous text remains an
`unclassified_reference` for source-owner review. The report includes path, line,
column, matched token and exact-line hash rather than copying whole source lines.
It does not rewrite files or infer that a test, quotation, or old document can be
ignored merely from its directory name.

Report mode exits zero when scanning succeeds, even if `ok` is false. This allows
inventory before existing references are corrected; it is not a compliance gate.
`--strict` exits 1 for findings. Policy/input errors exit 2 in either mode. Strict
enforcement will be connected to release and PR gates after current owned
surfaces have been remediated and visually reviewed.

## Exact exceptions

`ls/config/branding.json` owns schema version 1, `exceptions`, `visual_reviews` and
`binary_reviews`.
Each text exception has a repository-relative `path`, `line_sha256`, exact `token`,
positive `count`, `kind`, and a nonempty `reason`. Allowed kinds are
`compatibility_identifier`, `upstream_attribution`, `historical_evidence`, and
`negative_test`. The line hash is SHA-256 of UTF-8 text without its line terminator.
The count is the number of matching token occurrences on identical lines in that
file. An edited line, extra occurrence, removed file, or now-canonical reference
invalidates the exception and produces `stale_exception`.

Use exceptions only for evidence that must retain exact spelling. Correct owned
display text instead of suppressing it. Do not add broad directory exclusions,
wildcard exceptions, or an exception merely to make a release pass.

## Visual and accessibility evidence

Every inventoried image or PDF requires a hash-bound `visual_reviews` entry with
`path`, `sha256`, `reviewed_text`, `accessibility_evidence`, `reviewer`, and
`reviewed_at`. Inspect the actual rendered asset: OCR and text search do not prove
embedded branding. Record either the reviewed embedded text or that the asset
has no brand-bearing text, and identify the matching accessibility text in its
consumer. Review assets without an unrelated redesign. A changed hash or removed
asset invalidates its approval; a new asset requires review.

Unknown binary files produce `binary_classification_required`; recognized image
signatures require visual review even without a normal image extension. A
nonvisual binary may have an exact `binary_reviews` entry with `path`, `sha256`
and a nonempty classification `reason`. Changing or removing that binary makes
the review stale. Do not classify rendered images as nonvisual binary data.

The initial policy intentionally contains no accepted exceptions or visual
reviews. Repository-wide branding compliance remains unproven until the text,
generated output, installed runtime, compatibility, transport, artifact and visual
checks all pass. The validator supports that evidence; it does not substitute
for installed-artifact and visual acceptance.

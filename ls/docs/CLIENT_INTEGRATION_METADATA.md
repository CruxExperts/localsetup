# Client integration metadata

`ls/config/clients.yaml` owns client families and variants.
`ls/config/platforms.yaml` is its generated installation projection; update the
owner and run `localsetup client-registry generate`, then
`localsetup client-registry check` to validate the projection.
CLI, IDE, and application variants remain separate records even when they share
skill directories. The existing `verification.classification` selects a check
method; it is not evidence that a host check succeeded.

An optional `integration` object records lifecycle, installation guidance, and
qualification results separately. Existing records without it retain their
current behavior until their owning profile is reverified. A missing object
must not be interpreted as successful qualification.

```yaml
integration:
  lifecycle: active
  installation:
    method: manual
    instructions: Follow the vendor guide cited in research.sources.
  qualification:
    catalog: bounded
    filesystem: not-run
    host: not-run
    evidence:
      - kind: documentation
        reference: ls/docs/CLIENT_INTEGRATION_METADATA.md
  limitations:
    - Host authentication and functional execution have not been qualified.
```

- `lifecycle` is `active`, `retained-only`, or `unsupported`. A retained-only or
  unsupported record cannot carry `compatibility` and therefore cannot project
  a fresh-install adapter. Historical receipts remain separate ownership
  evidence; this declaration does not authorize deleting them or their content.
- `installation.method` is `managed-release`, `vendor-installer`,
  `package-manager`, `editor-extension`, `application`, `manual`, or
  `unavailable`. `instructions` describes the installation route. Neither field
  is an executable recipe or authorization to install, authenticate, or update
  a third-party application.
- `qualification.catalog` is `implemented` or `bounded`. Filesystem qualification
  is `verified`, `not-run`, or `not-applicable`; host qualification additionally
  permits `blocked`. Catalog support and filesystem fixtures do not establish
  successful host installation or functional host behavior.
- Evidence entries have a `filesystem`, `host`, or `documentation` kind and a
  repository-relative reference or HTTPS URL. Each `verified` surface requires
  matching evidence. Bounded catalog support, blocked host qualification, and
  non-active lifecycle require explicit limitations.

Validation checks declarations and reference syntax, including rejection of
private state paths and URL user information. It does not execute evidence,
prove a linked report's claim, or establish that an arbitrary HTTPS destination
is public. Review exact evidence and its tested version/environment before
marking a surface verified. Machine-specific records stay private; public
metadata references only intentionally publishable tests and documentation.
Preserve upstream attribution and immutable historical audit evidence.

---
status: ACTIVE
version: 4.4
owner_skill: ls-framework-compliance
---

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

## GitHub Copilot profiles

The `github-copilot` family has independent `github-copilot-cli` and
`github-copilot-vscode` selectors. Both project repository skills to
`.agents/skills` and personal skills to `~/.agents/skills`. This is LocalSetup's
choice among documented native discovery paths, not a claim of upstream path
priority. Selecting both deduplicates physical writes while retaining separate
owners. Symlink and portable filesystem fixtures cover installation, partial
repository/personal detach, and custom-content preservation.

```bash
localsetup plan --target-directory PROJECT --tools github-copilot-cli github-copilot-vscode --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools github-copilot-cli github-copilot-vscode --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

These commands install LocalSetup skill adapters. They do not install or
activate Copilot, authenticate an account, or change native settings, permissions,
credentials, or sessions. Catalog and filesystem support are implemented; host
qualification remains `not-run`. Exact minimum versions and duplicate skill-root
precedence are unverified. Existing context may be discovered through `AGENTS.md`,
but policy insertion and personal instruction/configuration management are not
qualified by these profiles.

| Profile | Discovery and installation | Context and qualification boundary |
|---|---|---|
| GitHub Copilot CLI | Executable candidate `copilot`; select and verify a pinned official release artifact before installation. | Applicable instructions combine without a general precedence guarantee. `COPILOT_HOME` redirects personal instructions and configuration; its effect on skill roots is not assumed. |
| GitHub Copilot in VS Code | Executable candidate `code`, plus the intended editor profile and official Copilot activation. Command presence alone does not establish availability. | Personal, repository, and organization instructions have separate conflict priority. Effective settings, workspace, harness, trust, and remote environment affect discovery. |

CLI installation and skill paths are described in the official
[installation guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/install-copilot-cli)
and [skills guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills).
Its [instruction guide](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)
and [command reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference)
own instruction combination and `COPILOT_HOME` behavior. Native startup may
migrate legacy configuration to `settings.json`; do not start the client merely
to treat its configuration as a read-only probe.

VS Code's [Copilot setup guide](https://code.visualstudio.com/docs/setup/copilot),
[skill guide](https://code.visualstudio.com/docs/agent-customization/agent-skills),
and [instruction guide](https://code.visualstudio.com/docs/agent-customization/custom-instructions)
own editor activation and discovery. Check `chat.useAgentsMdFile`, effective
skill-location settings, and the selected harness before claiming native context
or skill loading. These profiles do not qualify Copilot cloud agents, Visual
Studio, JetBrains, or other application variants. Local filesystem tests do not
prove that a remote editor host can access the same paths.

## Cline profiles

The `cline` family has `cline-cli` and `cline-vscode` selectors for executable
and VS Code extension installation surfaces. Both use `.cline/skills` in the
repository and `~/.cline/skills` for personal skills. Selecting both retains
two logical owners while deduplicating writes. These variants share one native
skill contract; separate identifiers do not claim different runtime behavior.
Symlink and portable fixtures cover installation, verification, partial detach,
and preservation of custom content and native settings/session fixtures. Host
qualification remains `not-run`.

```bash
localsetup plan --target-directory PROJECT --tools cline-cli cline-vscode --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools cline-cli cline-vscode --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

The CLI discovery candidate is `cline`; the IDE identity is the official
`saoudrizwan.claude-dev` extension in the intended VS Code profile and extension
host. Editor executable presence alone does not establish Cline availability.
These commands install skill adapters only. Application installation, account
authentication, and provider selection remain separate.

Use the [official installation guide](https://docs.cline.bot/getting-started/installing-cline)
with a verified release artifact. Its CLI package and Node requirements differ
from [the inspected CLI source](https://github.com/cline/cline/blob/dac3b35ba485dbab3b5a73aca239b0d07ce071cf/apps/cli/package.json);
resolve that mismatch for the selected release before installation. Do not infer
a package migration or minimum compatible version from moving source.

The [skills guide](https://docs.cline.bot/customization/skills) documents the
selected native roots. Current source also lists common skill roots in the
[IDE loader paths](https://github.com/cline/cline/blob/dac3b35ba485dbab3b5a73aca239b0d07ce071cf/apps/vscode/src/core/storage/skill-directories.ts)
and [SDK shared paths](https://github.com/cline/cline/blob/dac3b35ba485dbab3b5a73aca239b0d07ce071cf/sdk/packages/shared/src/storage/paths.ts).
Those source observations do not establish released CLI wiring or installed
host behavior. LocalSetup keeps native projections; it does not combine all
mentioned roots into a verified search order. Duplicate names, toggles, custom
roots, enterprise policy, and minimum versions require host qualification.

The [configuration guide](https://docs.cline.bot/getting-started/config) and
[CLI reference](https://docs.cline.bot/cli/cli-reference) differ on legacy
settings/skill layout. Data-directory overrides do not prove that every
customization root moves. Preserve existing legacy directories, `~/.cline/data`,
credentials, sessions, databases, settings, plugins, hooks, and custom rules.
[Instruction discovery](https://docs.cline.bot/customization/cline-rules),
including `AGENTS.md`, is separate from skill discovery; policy insertion and
personal instruction management remain unqualified.

## Windsurf / Cascade retention

The `windsurf` family records the audited `windsurf-cascade` IDE identity.
LocalSetup treats it as **retained-only** while upstream availability guidance
conflicts. This is an installation policy, not a declaration that Cascade has
been retired. No fresh-install platform projection is emitted, so
`--tools windsurf-cascade` is rejected for fresh selection. Existing receipts
retain their client identity and recorded paths for verification, package
updates, and detach. Symlink and portable fixtures exercise that lifecycle
using a synthetic historical catalog; they do not certify a desktop build.

[The Cascade skills guide](https://docs.devin.ai/desktop/cascade/skills) confirms
repository `.agents/skills` and personal `~/.agents/skills`, alongside native
`.windsurf/skills` and `~/.codeium/windsurf/skills`. Retain existing native content;
do not duplicate projections or infer cross-root collision precedence.
[AGENTS.md discovery](https://docs.devin.ai/desktop/cascade/agents-md) supports
root and nested instructions, but this profile does not manage policy insertion.
[Rules and memories](https://docs.devin.ai/desktop/cascade/memories) are separate
from skills and do not establish a durable scheduler.

The [transition FAQ](https://docs.devin.ai/desktop/devin-desktop-faq) says Cascade
remains available through July after the June 2026 desktop rename, while
[current agent-selection guidance](https://docs.devin.ai/desktop/devin-local)
still describes Cascade selection and fallback. Neither definitive removal nor
universal availability is established by those conflicting statements.
Qualification is blocked pending an exact build and account where Cascade can
be selected, with its effective settings and harmless skill discovery checked.
Do not authenticate, change agent settings, or install an old build merely to
resolve this uncertainty without target-specific authority.

[Current downloads](https://devin.ai/download) supply Devin Desktop. The
`devin-desktop`, `surf`, and `windsurf` launcher candidates establish desktop
presence only. They do not prove Cascade availability. Devin Local and
JetBrains are outside this profile; never substitute their discovery contracts.
Native settings, MCP configuration, memories, sessions, workspaces, enterprise
policy, custom rules, and skills remain vendor/user-owned.

For a healthy existing receipt, retain scope and client selection by omitting
selectors during the recorded update:

```bash
localsetup verify --target-directory PROJECT
localsetup plan --target-directory PROJECT
localsetup update --target-directory PROJECT
```

`plan` is read-only; `update` applies the recorded package refresh. This does
not upgrade the desktop application or prove host compatibility. Automatic repository-only doctor repair is not qualified for this retained
profile: it returns a preservation blocker before client inference, even when
application is requested. Preserve the receipt and custom content and use a
verified backup or reviewed recorded-path recovery under the
[ownership guidance](ADAPTER_OWNERSHIP.md). Personal and combined repair retain
their recorded ownership routes. Do not replace an unhealthy receipt with fresh
profile selection.

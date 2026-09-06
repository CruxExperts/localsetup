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

## Amp CLI

The `amp` family provides the `amp-cli` selector, with repository
`.agents/skills` and personal `~/.agents/skills` projections. The executable
discovery candidate is `amp`; desktop, editor, web, and remote-agent surfaces
are outside this qualification. Catalog and filesystem fixtures are implemented;
installed host qualification remains `not-run`.

```bash
localsetup plan --target-directory PROJECT --tools amp-cli --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools amp-cli --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

`plan` describes the intended layout. Application performs a fresh static
collision preflight before managed writes. A conflict leaves existing origins
in place; do not rename, relocate, or delete user skills automatically. Selecting
multiple clients that share the chosen physical paths retains their logical
owners without duplicating writes. Personal and combined repair apply the same
collision guard before restoring exposure.

[Amp's skills documentation](https://ampcode.com/docs/customize/skills) resolves
duplicates by frontmatter `name`, with first occurrence winning. Its documented
local order begins with `~/.config/agents/skills`, `~/.agents/skills`, and
`~/.config/amp/skills`, followed by project/ancestor `.agents/skills` and
`.claude/skills`, then personal `~/.claude/skills`. Thus global content can
shadow project content. The guard scans those roots and checks both directions:
an existing source masking the planned skill, or a planned source masking
existing content. Different directory basenames do not avoid a name conflict.
Jointly planned projections and existing links to the same planned canonical
library are allowed. An unchanged portable counterpart also requires recorded
ownership, matching adapter/library metadata, and matching package content and
link metadata. Ordinary ownership checks still protect custom entries. Writes
through another client also check affected recorded Amp owners sharing the
physical path or updated library packages; known repository targets are included.

Frontmatter discovery is bounded to 4,096 directory entries and 16 KiB per
skill; accepting an owned portable counterpart additionally compares its package
content and link metadata with the intended payload. Unreadable or malformed metadata, unresolved entries, and symlink
roots block qualification. Exact runtime ancestor stopping/order, configured
paths, plugins, built-ins, remote repositories, and session reload behavior are
not qualified by this filesystem scan. It does not prove equivalence to the
effective Amp catalog. No automatic Amp command is invoked: skill discovery can
connect declared MCP servers, and reload can fetch remote sources.

[Plugin documentation](https://ampcode.com/docs/customize/plugins) establishes
XDG configuration overrides for plugins, not loose skills. A nondefault
`XDG_CONFIG_HOME` blocks this preflight until the effective loose-skill contract
is qualified; the guard does not silently replace the documented roots.
[Native settings](https://ampcode.com/docs/cli/settings), including configured
skill paths, permissions, MCP configuration, and thread visibility, remain
unmodified. [AGENTS.md guidance](https://ampcode.com/docs/customize/agents-md)
has its own ancestor/subtree and personal-file behavior; policy insertion and
private guidance management remain unqualified.

Use the [official installation route](https://ampcode.com/docs/cli) only with a
verified installer and selected release artifact. Authentication and upstream
background-update behavior require separate target qualification. Installing
LocalSetup skill adapters does not install Amp, configure its updater, or grant
account, network, or provider authority.

## Goose CLI

The `goose` family exposes `goose-cli`, using repository `.agents/skills` and
personal `~/.agents/skills`. The discovery candidate is `goose`; Goose Desktop
is a separate interface outside this qualification. Resource-bearing skill
packages, repository/personal/both ownership and symlink/portable projections
have filesystem fixtures. Installed host qualification remains `not-run`.

```bash
localsetup plan --target-directory PROJECT --tools goose-cli --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools goose-cli --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

The plan describes layout without creating Goose configuration. Application,
personal/combined repair, and writes affecting recorded Goose owners require a
fresh static configuration check before managed writes. Verification reports
`goose_skills_configured` with `scope: static-configuration` and
`host_verified: false`. Passing this prerequisite does not attest that a
particular Goose build or session can load skills.

On Linux/WSL and macOS, the qualified default file is
`~/.config/goose/config.yaml`. An explicit native Skills entry has this shape:

```yaml
extensions:
  skills:
    enabled: true
    type: platform
    name: skills
```

This example describes user-owned configuration, not an instruction to overwrite
an existing file. LocalSetup never enables extensions or runs Goose's native
configuration loader, which may migrate and save state. Missing, malformed,
ambiguous, oversized (over 256 KiB), aliased, or tool-restricted configuration
returns unknown; explicit native Skills `enabled: false` returns disabled.
Only absent or empty `available_tools` is qualified. System configuration at
`/etc/goose/config.yaml`, `GOOSE_PATH_ROOT`, `GOOSE_ADDITIONAL_CONFIG_FILES`,
`EXTENSIONS`, or a nondefault `XDG_CONFIG_HOME` requires separate effective-state
qualification. The checker does not merge these layers. Session/recipe overrides
and build availability remain outside the static predicate.

The [skills guide](https://goose-docs.ai/docs/guides/context-engineering/using-skills/)
and [Summon guide](https://goose-docs.ai/docs/mcp/summon-mcp/) describe a separate
Skills extension, while the [Skills extension page](https://goose-docs.ai/docs/mcp/skills-mcp/)
contains conflicting deprecation guidance. Therefore LocalSetup assumes neither
default activation nor substitution by Summon. Qualify the selected release and
session before relying on host behavior. Additional private-home discovery,
plugins, root precedence and duplicate-name resolution remain unqualified.

[Context files](https://goose-docs.ai/docs/guides/context-engineering/using-goosehints/)
include `AGENTS.md` and `.goosehints`; hierarchy and
`CONTEXT_FILE_NAMES` overrides are distinct from skill projection, and automatic
policy insertion remains unqualified. Native settings, keyring, sessions,
databases, recipes, plugins and custom extensions remain user-owned.
[Environment overrides](https://goose-docs.ai/docs/guides/environment-variables/)
require the effective configuration to be established separately. Use the
[official installation guidance](https://goose-docs.ai/docs/getting-started/installation/)
with a verified selected artifact; installing adapters does not install Goose,
authenticate, configure providers, or authorize network calls.

## Pi coding agent

The `pi` family provides `pi-cli`, with executable candidate `pi`, repository
`.agents/skills` and personal `~/.agents/skills`. LocalSetup projects directory
packages containing `SKILL.md` and supporting resources. Filesystem fixtures
cover both projection modes, shared owners, detach, and preservation of custom
skills and native state. Installed Pi qualification remains `not-run`.

```bash
localsetup plan --target-directory PROJECT --tools pi-cli --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools pi-cli --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

These commands manage filesystem ownership. Successful verification does not
establish that Pi trusts the project or has loaded its skills. Pi's
[skills documentation](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/docs/skills.md)
describes common and native roots, with project/ancestor discovery conditional
on trust. Native `.pi/skills` and `~/.pi/agent/skills` can accept loose Markdown
skills; LocalSetup does not relocate or convert them into common packages.
Duplicate frontmatter names retain the first discovery with a warning. Exact
source precedence, settings filters, explicit `--skill` paths and installed
runtime discovery need separate qualification; `--no-skills` does not suppress
all explicitly supplied skills.

[Pi trust and settings](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/docs/settings.md)
are user-owned. Trust may allow project settings, missing package installation,
and extension execution. LocalSetup never approves trust, changes
`~/.pi/agent/trust.json`, supplies approval flags, or invokes Pi to validate an
adapter. Noninteractive Pi modes do not prompt for trust; effective saved,
parent, default and command-line decisions determine loading. Review those
controls in the intended host session rather than treating adapter installation
as consent. Settings at `.pi/settings.json` and `~/.pi/agent/settings.json`,
resource filters, packages and extensions remain unchanged.

The [CLI guide](https://github.com/earendil-works/pi/blob/9767ba275f3e9a5ee0f5c5342249b629ab1b2282/packages/coding-agent/README.md)
documents context discovery and `AGENTS.override.md` replacement within a
directory; do not overwrite overrides or equate context and skill trust rules.
Automatic policy insertion is unqualified. `PI_CODING_AGENT_DIR` and
`PI_CODING_AGENT_SESSION_DIR` can redirect native state. Auth, models, sessions,
trust records and system-prompt overrides remain outside adapter ownership.

Use the current official installation guide with a verified selected artifact.
The cited source uses `@earendil-works/pi-coding-agent`; historical package names
require release/registry reconciliation before installation. Source metadata is
not proof of package availability. Startup network behavior and authentication
also require separate target qualification; no Pi command is invoked here.
Pi, OMP and LSCli are distinct runtimes. Common skill-package shape does not
establish extension, provider, permission, session, MCP or sandbox compatibility.

## Hermes Agent

The `hermes` family exposes `hermes-agent`, with executable candidate `hermes`.
It writes independent portable packages to repository `.hermes/skills` and the
explicit default personal profile `~/.hermes/skills`. Native copies keep mutable
skills isolated from the canonical LocalSetup library; they are not read-only.
Saved package baselines and independent ownership receipts prevent automatic
replacement or removal of native edits or deletions. Preserve and reconcile those
changes before retrying update, repair, detach or rollback. Keep Hermes writers
quiescent during maintenance; LocalSetup locks coordinate LocalSetup operations.

```bash
localsetup plan --target-directory PROJECT --tools hermes-agent --skill-scope both --skills ls-context --mode portable
localsetup install --target-directory PROJECT --tools hermes-agent --skill-scope both --skills ls-context --mode portable --apply
localsetup verify --target-directory PROJECT
```

Symlink mode is refused. Personal selection explicitly targets the default
profile; a nondefault `HERMES_HOME` refuses these writes. Named profiles, sticky
CLI selection and context-local API overrides need separate qualification. These
commands do not determine or change a running session's selected profile.
[Hermes profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/)
keep native configuration and state separate; do not use default-profile adapter
success as evidence that another profile has loaded its skills.

[Native skill discovery](https://github.com/NousResearch/hermes-agent/blob/245e48008fa814b3251f50755eb656bd9fb86cb1/agent/skill_utils.py)
requires a Git root and explicit project trust for project packages. Discovery
can be disabled or content quarantined. LocalSetup does not approve trust or add
`skills.external_dirs`. Shared-home external sources require native configuration
and can be writable; pointing Hermes at canonical LocalSetup symlinks would not
provide the copy isolation implemented here. Resource precedence, categorized
name ambiguity and effective session loading require host verification.

Native configuration, profiles, `SOUL.md`, sessions, databases, memory, cron,
gateway state, plugins, vendor manifests and custom skills remain user-owned.
Hermes-specific context and `AGENTS.override.md` can affect instruction loading;
context discovery does not establish skill trust. `/reload-skills` or
`/reload_skills` rescans skills; credential reload and MCP reload are separate
operations. Use the official installation guide with a verified selected artifact.
The adapter performs no Hermes installation, startup, authentication or provider
call. Filesystem lifecycle fixtures are qualified; installed-host behavior remains
`not-run`.

## Qwen Code

The `qwen-code` family exposes `qwen-code-cli`, with executable candidate `qwen`.
Repository `.agents/skills` and personal `~/.agents/skills` support the common
LocalSetup directory-package projection. Filesystem fixtures cover symlink and
portable modes, resources, shared owners, detach and native-content preservation.
Installed Qwen qualification remains `not-run`.

```bash
localsetup plan --target-directory PROJECT --tools qwen-code-cli --skill-scope both --skills ls-context
localsetup install --target-directory PROJECT --tools qwen-code-cli --skill-scope both --skills ls-context --apply
localsetup verify --target-directory PROJECT
```

The [v0.23.0 storage source](https://github.com/QwenLM/qwen-code/blob/98a9c964158697dd5631d15a62174684ff7bbb53/packages/core/src/config/storage.ts)
includes both `.qwen` and `.agents` skill providers. `QWEN_HOME` relocates the
native user root; common personal discovery remains under the user's home.
The [release skill manager](https://github.com/QwenLM/qwen-code/blob/98a9c964158697dd5631d15a62174684ff7bbb53/packages/core/src/skills/skill-manager.ts)
uses project, user, extension and bundled precedence, with native `.qwen` ahead
of common `.agents` within a scope. LocalSetup preserves native same-name skills;
putting a package in common storage does not override them. This is verified-at
source evidence, not a claim that v0.23.0 first introduced the feature.

Bare mode disables skill loading, and safe mode restricts it to bundled skills.
Settings, enablement and project-root handling also affect the effective inventory.
Source link validation accepts external directory targets, but successful adapter
verification still establishes filesystem exposure, not activation, resource
execution or a permission grant. Qualify those behaviors in the intended release
and session before claiming host support.

Native `QWEN.md`, settings, extensions, credentials, sessions, runtime overrides
and generated AutoSkill content remain user-owned. Keep learned skills in native
locations, separate from installed canonical packages. This adapter does not
redirect creation, rewrite native collisions, change skill settings or invoke
Qwen. Use official installation guidance with a verified selected artifact;
installation, authentication and functional host qualification are separate.

The [versioned skill guide](https://github.com/QwenLM/qwen-code/blob/98a9c964158697dd5631d15a62174684ff7bbb53/docs/users/features/skills.md)
limits automatic curation to native `auto-skill-*` directories carrying the
`source: auto-skill` marker. Ordinary projected packages are outside that
selection; this is not protection against general agent file or shell tools.
The [memory guide](https://github.com/QwenLM/qwen-code/blob/98a9c964158697dd5631d15a62174684ff7bbb53/docs/users/features/memory.md)
documents `QWEN.md`, existing `AGENTS.md` and personal project
`.qwen/QWEN.local.md`; LocalSetup does not duplicate or insert native context.
Effective context precedence remains unqualified, and generated memory settings
and optional synchronization remain untouched.

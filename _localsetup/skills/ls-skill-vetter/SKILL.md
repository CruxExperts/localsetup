---
name: ls-skill-vetter
description: "Security-first skill vetting for AI agent skills. Use before installing any skill from public registries (e.g. skill hubs, GitHub) or other sources. Checks for red flags, permission scope, and suspicious patterns."
metadata:
  version: "1.2"
---

# Skill Vetter

Security-first vetting protocol for AI agent skills. **Never install a skill without vetting it first.**

## When to Use

- Before installing any skill from a public registry (e.g. skill hub, GitHub)
- Before running skills from GitHub repos
- When evaluating skills shared by other agents
- Anytime you're asked to install unknown code

## Vetting Protocol

### Step 1: Source Check

```
Questions to answer:
- [ ] Where did this skill come from?
- [ ] Is the author known/reputable?
- [ ] How many downloads/stars does it have?
- [ ] When was it last updated?
- [ ] Are there reviews from other agents?
```

### Step 2: Spec and Metadata Validation (MANDATORY)

Verify the candidate skill is a valid Agent Skill before reviewing behavior:

```
Required checks:
- [ ] Skill directory contains SKILL.md.
- [ ] Frontmatter includes name and description.
- [ ] name matches the skill directory and uses lowercase letters, numbers, and hyphens.
- [ ] description explains what the skill does and when to use it.
- [ ] metadata.version is present or the absence is documented.
- [ ] Optional sidecars such as _meta.json match SKILL.md metadata, or drift is reported.
- [ ] Optional validation command was run when available: `agentskills validate <skill-dir>`.
```

Treat `SKILL.md` frontmatter as the canonical local metadata. Sidecars are provenance or export metadata only; they must not override the local skill/catalog version.

### Step 3: Code Review (MANDATORY)

Read ALL files in the skill. Check for these **RED FLAGS**:

```
REJECT IMMEDIATELY IF YOU SEE:

- curl/wget to unknown URLs
- Sends data to external servers
- Requests credentials/tokens/API keys
- Reads ~/.ssh, ~/.aws, ~/.config without clear reason
- Accesses MEMORY.md, USER.md, SOUL.md, IDENTITY.md
- Uses base64 decode on anything
- Uses eval() or exec() with external input
- Modifies system files outside workspace
- Installs packages without listing them
- Network calls to IPs instead of domains
- Obfuscated code (compressed, encoded, minified)
- Requests elevated/sudo permissions
- Accesses browser cookies/sessions
- Touches credential files

```

### Step 4: Permission Scope

```
Evaluate:
- [ ] What files does it need to read?
- [ ] What files does it need to write?
- [ ] What commands does it run?
- [ ] Does it need network access? To where?
- [ ] Is the scope minimal for its stated purpose?
```

### Step 5: Risk Classification

| Risk Level | Examples | Action |
|------------|----------|--------|
| LOW | Notes, weather, formatting | Basic review, install OK |
| MEDIUM | File ops, browser, APIs | Full code review required |
| HIGH | Credentials, trading, system | Human approval required |
| EXTREME | Security configs, root access | Do NOT install |

## Output Format

After vetting, produce this report:

```
SKILL VETTING REPORT

Skill: [name]
Source: [registry / GitHub / other]
Author: [username]
Version: [version]

METRICS:
- Downloads/Stars: [count]
- Last Updated: [date]
- Files Reviewed: [count]

RED FLAGS: [None / List them]

SPEC VALIDATION:
- Status: [PASS / FAIL / NOT RUN]
- Metadata drift: [None / List mismatches]

PERMISSIONS NEEDED:
- Files: [list or "None"]
- Network: [list or "None"]
- Commands: [list or "None"]

RISK LEVEL: [LOW / MEDIUM / HIGH / EXTREME]

VERDICT: [SAFE TO INSTALL / WARNING INSTALL WITH CAUTION / DO NOT INSTALL]

NOTES: [Any observations]

```

## Quick Vet Commands

For GitHub-hosted skills:
```bash
# Check repo stats
curl -s "https://api.github.com/repos/OWNER/REPO" | jq '{stars: .stargazers_count, forks: .forks_count, updated: .updated_at}'

# List skill files
curl -s "https://api.github.com/repos/OWNER/REPO/contents/skills/SKILL_NAME" | jq '.[].name'

# Fetch and review SKILL.md
curl -s "https://raw.githubusercontent.com/OWNER/REPO/main/skills/SKILL_NAME/SKILL.md"
```

## Trust Hierarchy

1. **Official skills from a trusted registry or vendor** - Lower scrutiny (still review)
2. **High-star repos (1000+)** - Moderate scrutiny
3. **Known authors** - Moderate scrutiny
4. **New/unknown sources** - Maximum scrutiny
5. **Skills requesting credentials** - Human approval always

## Remember

- No skill is worth compromising security
- When in doubt, don't install
- Ask your human for high-risk decisions
- Document what you vet for future reference

---

Security bias is intentional.

# Linux Patcher - agent host Skill

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](../../../LICENSE)
[![agent host](https://img.shields.io/badge/agent host-Skill-orange)](https://agent-host.ai)

Automated Linux server patching with PatchMon integration for agent host.

## 🎯 Features

- ✅ **Ubuntu fully tested** - Production-ready
- ⚠️ **10+ distributions supported** - Debian, RHEL, AlmaLinux, Rocky, CentOS, Amazon Linux, SUSE (untested)
- 🔒 **Security-focused** - Restricted sudo, SSH key auth
- 🤖 **PatchMon integration** - Automatic host detection
- 🐳 **Smart Docker detection** - Auto-detects and updates containers
- 📊 **Visual workflow diagrams** - Easy to understand
- 🚀 **Chat-based interface** - "Update my servers" just works
- 🔄 **Dry-run mode** - Preview changes before applying

## 🚀 Quick Start

### Installation

```bash
# Option 1: Install from file
agent-host skill install linux-patcher.skill

# Option 2: Install from ClawHub (when published)
install this skill through your agent skill manager

# Option 3: Install from this repo
git clone https://github.com/JGM2025/linux-patcher-skill
cd linux-patcher-skill
agent-host skill install .
```

### Initial Setup

```bash
# 1. Read the setup guide
cd ~/.agent-host/workspace/skills/linux-patcher
cat references/setup.md

# 2. Configure SSH keys
ssh-keygen -t ed25519 -C "agent-host-patching" -f ~/.ssh/id_agent-host
ssh-copy-id -i ~/.ssh/id_agent-host.pub admin@targethost

# 3. Collect PatchMon URL/credentials out of band if you plan to add a tested API client

# 4. Generate a dry-run plan
python scripts/patch_cli.py auto --dry-run
```

### Usage

**Via agent host chat (recommended):**

```
You: "Update my servers"
→ Updates packages + Docker containers automatically

You: "Update my servers, excluding docker"
→ Updates packages only, containers keep running

You: "What servers need patching?"
→ Queries PatchMon for update status
```

**Direct command line:**

```bash
# Automatic mode (PatchMon)
python scripts/patch_cli.py auto

# Skip Docker updates
python scripts/patch_cli.py auto --skip-docker

# Dry-run (preview only)
python scripts/patch_cli.py auto --dry-run

# Manual single host
python scripts/patch_cli.py host-only admin@webserver.example.com
python scripts/patch_cli.py host-full admin@webserver.example.com /opt/docker
```

## 📋 Prerequisites

### Required

- **agent host** installed and running
- **SSH client** with key authentication
- **curl** and **jq** for PatchMon integration
- **Passwordless sudo** on target hosts (restricted to patching commands)
- **PatchMon** installed (required to check which hosts need updating)
  - Does NOT need to be on the agent host host
  - Download: https://github.com/PatchMon/PatchMon
  - Docs: https://docs.patchmon.net

### For Automatic Host Detection

- **PatchMon server** (required for automatic mode)
  - **Important:** Does NOT need to be on the same server as agent host
  - Install on any accessible server (separate host recommended)
  - agent host queries PatchMon via HTTPS API
  - Download: https://github.com/PatchMon/PatchMon

### Optional

- **Docker** on target hosts (for container updates)
- **Docker Compose** on target hosts

**Note:** You can use this skill without PatchMon by manually specifying hosts, but automatic detection of which hosts need updates requires PatchMon.

## 📖 Documentation

Complete documentation is included in the skill:

- **[SKILL.md](SKILL.md)** - Main usage guide and features
- **[references/setup.md](references/setup.md)** - Complete setup with security best practices
- **[references/workflows.md](references/workflows.md)** - Visual workflow diagrams
- **[references/patchmon-setup.md](references/patchmon-setup.md)** - PatchMon installation

## 🌍 Supported Distributions

| Distribution | Package Manager | Status |
|--------------|-----------------|--------|
| Ubuntu | apt | ✅ Fully tested |
| Debian | apt | ⚠️ Supported (untested) |
| Amazon Linux 2 | yum | ⚠️ Supported (untested) |
| Amazon Linux 2023 | dnf | ⚠️ Supported (untested) |
| RHEL 7 | yum | ⚠️ Supported (untested) |
| RHEL 8+ | dnf | ⚠️ Supported (untested) |
| AlmaLinux | dnf | ⚠️ Supported (untested) |
| Rocky Linux | dnf | ⚠️ Supported (untested) |
| CentOS 7 | yum | ⚠️ Supported (untested) |
| CentOS 8+ | dnf | ⚠️ Supported (untested) |
| SUSE/OpenSUSE | zypper | ⚠️ Supported (untested) |

**Testing needed!** If you use this skill on untested distributions, please report results via issues.

## 🔒 Security

This skill is designed with security as a priority:

- **No passwords stored** - SSH key authentication only
- **Restricted sudo** - Only specific commands allowed (no `NOPASSWD: ALL`)
- **Principle of least privilege** - Minimal permissions granted
- **Audit trail** - All actions logged via syslog
- **Safe testing** - Dry-run mode available

See [references/setup.md](references/setup.md) for complete security configuration.

## 🎓 Examples

### Example 1: Automatic updates via PatchMon
```bash
# Query PatchMon, detect hosts, update everything
python scripts/patch_cli.py auto
```

### Example 2: Skip Docker updates
```bash
# Update packages only, leave containers running
python scripts/patch_cli.py auto --skip-docker
```

### Example 3: Test before applying
```bash
# Preview what would be updated
python scripts/patch_cli.py auto --dry-run

# Review output, then apply
python scripts/patch_cli.py auto
```

### Example 4: Via agent host chat
```
You: "Update my servers"
agent host: Queries PatchMon → Updates 4 hosts → Reports "✓ All hosts updated successfully"
```

### Example 5: Schedule automated patching
```bash
# Run nightly at 2 AM
cron add --name "Nightly Patching" \
  --schedule "0 2 * * *" \
  --task "cd ~/.agent-host/workspace/skills/linux-patcher && python scripts/patch_cli.py auto"
```

## 🤝 Contributing

Contributions welcome! Especially:

- Testing on untested distributions
- Bug reports and fixes
- Documentation improvements
- Feature requests

Please open an issue or pull request.

## 📄 License

MIT License - See [LICENSE](../../../LICENSE) file for details.

## 🆘 Support

- **Documentation:** See SKILL.md, references/setup.md, references/workflows.md
- **Issues:** https://github.com/JGM2025/linux-patcher-skill/issues
- **agent host Community:** https://discord.com/invite/clawd
- **PatchMon:** https://github.com/PatchMon/PatchMon

## 🎉 Acknowledgments

- Built for [agent host](https://agent-host.ai)
- Integrates with [PatchMon](https://github.com/PatchMon/PatchMon)
- Inspired by the need for simple, secure server patching

---

**Note:** Always test in a non-production environment first, especially on untested distributions.

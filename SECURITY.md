# Security

## Reporting a vulnerability

If you believe you have found a security vulnerability in Localsetup v3, please report it responsibly:

1. **Do not** open a public Issue for security-sensitive findings.
2. Open a **[private vulnerability report](https://github.com/cptnfren/localsetup/security/advisories/new)** (if enabled) or contact the maintainer via the [Contact Us](https://www.cruxexperts.com/) form at Crux Experts LLC, referencing "Localsetup v3 security."
3. Include a clear description, steps to reproduce, and impact if possible.

We will acknowledge receipt and work with you to understand and address the issue. We ask that you allow reasonable time for a fix before any public disclosure.

## Scope

- This policy applies to the Localsetup v3 framework (this repository): install scripts, deploy and verification tools, skills, and documentation.
- Out-of-scope: vulnerabilities in third-party tools (Cursor, Claude Code, Codex, OpenClaw, Git, Bash, PowerShell) or in code that users add when using the framework.

## Security practices in the framework

- No secrets or PII in the repository; see invariants in the framework context (engine/repo separation).
- Install and deploy use standard Git clone and file copy; no arbitrary remote code execution beyond the install script you invoke.
- Human-in-the-loop is required for destructive or privileged operations where specified. In the tmux shared-session workflow, the agent discovers sudo state (already valid, timeout, whether sudo is needed), then requests one human trigger (user joins the session, runs `sudo -v && echo SUDO_READY`); after that the agent batches all sudo commands until the validity window expires and does not prompt again within that window.

---

<p align="center">
<strong>Author:</strong> <a href="https://github.com/cptnfren">Slavic Kozyuk</a><br>
<strong>Copyright</strong> © 2026 <a href="https://www.cruxexperts.com/">Crux Experts LLC</a> – Innovate, Automate, Dominate.
</p>

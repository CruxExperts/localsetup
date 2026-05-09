# Tmux ops tool: remote (VMs, SSH, Docker)

**Purpose:** Use the tmux_ops workflow when the tmux server runs on a different host than where you run the command.

## Config

- **REMOTE_TMUX_HOST** - Hostname or IP of the machine where tmux runs. When set, the `tmux_ops` wrapper runs the Python tool over SSH and returns the same JSON.
- **REMOTE_TMUX_CWD** - Optional repo path on the remote. Default: `/opt/devzone/devops`.

## Usage

From repo root:

```bash
export REMOTE_TMUX_HOST=sh0t
./_localsetup/tools/tmux_ops pick
./_localsetup/tools/tmux_ops probe -t ops
./_localsetup/tools/tmux_ops run -t ops -- sudo apt update
```

If a run returns `status: "running"`, keep watching it by run ID:

```bash
./_localsetup/tools/tmux_ops status -t ops --run-id <run_id> --wait --timeout 120
```

Interrupt only through the managed cancel path:

```bash
./_localsetup/tools/tmux_ops cancel -t ops --run-id <run_id>
```

Session names, state paths, and log paths refer to the remote host.

## When not to set it

If you use Cursor Remote SSH and the agent runs on the same host as tmux, do **not** set REMOTE_TMUX_HOST. Run `tmux_ops` directly.

## Reference

- Skill: **ls-tmux-shared-session-workflow**
- Tool: `_localsetup/tools/tmux_ops` (`pick`, `probe -t SESSION`, `run -t SESSION -- CMD`, `status -t SESSION`, `cancel -t SESSION --run-id ID`)

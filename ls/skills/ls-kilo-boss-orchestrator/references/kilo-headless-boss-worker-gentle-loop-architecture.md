# Kilo Headless Boss-Worker Gentle Loop Architecture

## Purpose

This skill coordinates a small headless Kilo execution loop in a target repository without making generated adapter trees part of the Localsetup source boundary.

## Components

- `boss_ctl.py`: initializes state, enqueues structured task cards, dispatches primary and verifier workers, evaluates consensus, finalizes passed tasks, and runs lease recovery.
- `kilo_headless_runner.py`: executes one validated `kilo run ...` argv list with `shell=False`, records stdout/stderr, and emits failure-router metadata when available.
- `StateStore`: owns repo-local JSON/JSONL state below `.kilo/state/orchestrator/`.
- `consensus.py`: compares primary and verifier results and emits `gate_passed` plus `requires_tiebreaker`.

## Control Flow

1. A task card is enqueued from YAML with `session_id` and `command_argv`.
2. Dispatch claims a TTL lease, writes primary and verifier task cards, and records session metadata.
3. Each worker executes only allowlisted `kilo run ...` argv with non-interactive environment flags.
4. Consensus records whether the gate passed and whether a tiebreaker is mandatory.
5. Finalize only completes the task when the gate passed and no tiebreaker is required.
6. Watchdog reclaims orphan or expired leases and requeues or deadletters the task according to attempt limits.

## Safety Invariants

- Task commands are structured argv, not shell strings.
- The executable/subcommand allowlist is `kilo run`.
- Free-form shell command strings are rejected before execution; shell-looking text inside validated argv entries remains literal data.
- Leases expire based on `start_ts + ttl_seconds` and cannot block dispatch forever.
- A High/Critical disagreement must be adjudicated before completion.

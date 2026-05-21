# QC Severity Policy

- `critical`: active secret exposure, release artifact leak, or workflow path that can run untrusted code with write credentials.
- `high`: release-blocking package boundary violation, privileged workflow without fork guard, or reproducible security-sensitive failure.
- `medium`: correctness, drift, or configuration issue that requires maintainer planning.
- `low`: hygiene issue or advisory recommendation with low immediate blast radius.

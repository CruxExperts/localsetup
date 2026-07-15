# Version Matrix

This matrix is a snapshot, not a policy. It was verified on 2026-07-05 UTC from
npm registry metadata and Node release metadata. Run
`node scripts/verify-current-versions.mjs --json` from the skill root for a
fresh machine-readable view.

## Packages

| Package | Stable tag | Stable version | Non-stable tags checked | Key compatibility |
|---|---:|---:|---|---|
| `next` | `latest` | `16.2.10` | `canary: 16.3.0-canary.78`, `beta: 16.0.0-beta.0`, `rc: 15.0.0-rc.1` | Node `>=20.9.0`; React peers `^18.2.0 || 19.0.0-rc-de68d2f4-20241204 || ^19.0.0` |
| `react` | `latest` | `19.2.7` | `canary`, `experimental`, `next`, `beta`, `rc` tags exist | Match `react-dom` exactly unless the project documents otherwise. |
| `react-dom` | `latest` | `19.2.7` | `canary`, `experimental`, `next`, `beta`, `rc` tags exist | Peer dependency: `react ^19.2.7`. |

## Node Release Lines

| Line | Status on 2026-07-05 | Latest dist entry checked | Notes |
|---|---|---:|---|
| `20.x` | EOL | `v20.20.2` | Iron ended 2026-04-30. Do not choose for new production baselines. |
| `22.x` | Maintenance LTS | `v22.23.1` | Jod ends 2027-04-30. |
| `24.x` | Active LTS | `v24.18.0` | Krypton is the preferred production baseline when supported by the project and host. |
| `25.x` | EOL | `v25.9.0` | Ended 2026-06-01. Avoid for new production baselines. |
| `26.x` | Current | `v26.4.0` | Becomes LTS on the scheduled date if the release plan holds. Avoid as a default production baseline. |

## Guidance

- Next.js `>=20.9.0` is a minimum engine range, not a production
  recommendation.
- Prefer Active LTS for new production Node baselines when the deployment
  platform supports it.
- Maintenance LTS can be valid for existing systems, but plan migrations before
  the end date.
- Current releases are useful for compatibility testing, not default production
  deployment.

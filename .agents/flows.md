# Flow Registry

> All flows and their current status. Updated as flows are created, implemented, and archived.

## Active Flows

| Flow ID | Description | Beads Epic | Location |
|---------|-------------|------------|----------|
| idempotency-battery | Idempotency-Key battery: dedupe retried POST/PATCH (replay + 409 in-flight + 422 fingerprint) | litestar-batteries-va8 | [./specs/idempotency-battery/](./specs/idempotency-battery/) |

## Archived Flows

| Flow ID | Description | Completed | Location |
|---------|-------------|-----------|----------|
| project-foundation | Dev toolchain + CI (ruff, mypy, pyright, pytest, GH Actions matrix) | 2026-07-23 | [./archive/project-foundation/](./archive/project-foundation/) |
| health-battery | First battery: HealthPlugin (liveness + readiness) | 2026-07-23 | [./archive/health-battery/](./archive/health-battery/) |
| health-timeout | Per-check readiness timeout (`HealthCheck.timeout` → 503 instead of hanging) | 2026-07-30 | [./archive/health-timeout/](./archive/health-timeout/) |

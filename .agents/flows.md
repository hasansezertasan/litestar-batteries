# Flow Registry

> All flows and their current status. Updated as flows are created, implemented, and archived.

## Active Flows

| Flow ID | Description | Beads Epic | Location |
|---------|-------------|------------|----------|
| health-timeout | Per-check readiness timeout (`HealthCheck.timeout` → 503 instead of hanging) | litestar-batteries-8lt | [./specs/health-timeout/](./specs/health-timeout/) |

## Archived Flows

| Flow ID | Description | Completed | Location |
|---------|-------------|-----------|----------|
| project-foundation | Dev toolchain + CI (ruff, mypy, pyright, pytest, GH Actions matrix) | 2026-07-23 | [./archive/project-foundation/](./archive/project-foundation/) |
| health-battery | First battery: HealthPlugin (liveness + readiness) | 2026-07-23 | [./archive/health-battery/](./archive/health-battery/) |

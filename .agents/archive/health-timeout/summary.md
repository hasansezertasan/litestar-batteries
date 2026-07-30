# Archive Summary: health-timeout

**Archived:** 2026-07-30
**Status:** Complete
**Beads epic:** litestar-batteries-8lt (+ .1/.2/.3, all closed) — commit `65c0f83`

## What shipped

Optional per-check readiness timeout for the health battery. `HealthCheck.timeout: float | None = None`
(opt-in; `None` = unbounded, default unchanged). When set, the readiness check runs under
`asyncio.wait_for`; a timeout surfaces as a `CheckResult` error → `503`, so a stalled dependency no
longer hangs `GET /health/ready` (CodeRabbit finding on PR #2).

## Elevated Patterns

- **Python 3.10 is in the CI matrix → no 3.11+ stdlib APIs in `src`** (`asyncio.wait_for`, not
  `asyncio.timeout()`). → `patterns.md`

## Knowledge updates

- `knowledge/architecture.md` — health battery reference now documents the per-check `timeout` field
  and the `asyncio.TimeoutError`-before-`Exception` handler ordering.

## Verification

TDD (Red → Green); full gate green (ruff, mypy strict, pyright strict, pytest); 10 tests, 100% coverage.

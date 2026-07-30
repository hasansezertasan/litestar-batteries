# Spec: health-timeout (per-check readiness timeout)

> Beads epic: `litestar-batteries-8lt`. Beads is the source of truth for task status — do **not**
> hand-edit checkboxes; sync from Beads. High-Definition Worksheet: implementable with zero prior
> context. Extends the shipped **health-battery** (`src/litestar_batteries/health/`).

## Problem

CodeRabbit (PR #2) flagged that an arbitrary async `HealthCheck` can `await` forever, so
`GET /health/ready` hangs indefinitely if an external service stalls. `readiness()`
(`controller.py:43-50`) awaits each `hc.check()` with no time bound.

## Goal

Add an **optional per-check timeout** so a stalled check fails fast as a `503` instead of hanging:

```python
from litestar_batteries import HealthCheck, HealthConfig

HealthConfig(checks=[
    HealthCheck("db", db_ping, timeout=5.0),   # bounded: 503 if it takes >5s
    HealthCheck("cache", cache_ping),          # timeout=None -> unbounded (unchanged)
])
```

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Where the timeout lives | **Per-check only** — `HealthCheck.timeout: float \| None = None` | Per-check tuning; no global `HealthConfig.check_timeout` field. |
| Default value | **`None`** (opt-in, no timeout) | Zero behavior change for existing users; the hang is bounded only once an operator sets a value. |
| Primitive | **`asyncio.wait_for(hc.check(), hc.timeout)`** | Stdlib; works on Python 3.10. `asyncio.timeout()` context manager is 3.11+, so it is **not** used (repo supports 3.10+). |
| Timeout surfacing | `CheckResult(status="error", error=f"timed out after {timeout}s")` → overall `503` | Reuses the existing failed-check path; no new response shape. |
| Check ordering | **Unchanged** — sequential, registration order | Out of scope; a stalled check no longer blocks the rest once its own timeout fires. |

## Affected surfaces (grounded)

- `src/litestar_batteries/health/models.py:33-38` — `@dataclass(frozen=True) HealthCheck(name, check)`; add `timeout` field.
- `src/litestar_batteries/health/controller.py:43-50` — the `for hc in checks` loop that awaits `hc.check()`.
- `tests/test_health.py` — add timeout coverage (mirrors existing `create_test_client` sync-client style).
- No change to public exports (`__init__.py`): `timeout` is a new field on the already-exported `HealthCheck`.

## Tasks

### [x] Task 1 — TDD: failing tests for per-check timeout (`litestar-batteries-8lt.1`) [65c0f83]

Add to `tests/test_health.py` (write BEFORE impl → Red; `timeout=` kwarg does not exist yet):

- a **slow** async helper (e.g. `await asyncio.sleep(...)`) wrapped in `HealthCheck(..., timeout=<short>)`
  → `GET /health/ready` returns `503` and that check's `CheckResult.error` mentions a timeout.
- `timeout=None` (default) → a quick check still returns `200`; the await is unbounded.
- a fast check with a **generous** timeout → `200`.

- **Acceptance:** new tests fail before impl (Red); they reference `HealthCheck(..., timeout=...)`.

### [x] Task 2 — Add `HealthCheck.timeout` + wrap await in `asyncio.wait_for` (`litestar-batteries-8lt.2`) [65c0f83] — depends on Task 1

`models.py` — add to the frozen `HealthCheck` dataclass:

```python
timeout: float | None = None
"""Optional per-check timeout in seconds; ``None`` means no timeout."""
```

`controller.py` `readiness()` — bound each await and surface a timeout as a check error:

```python
import asyncio
...
for hc in checks:
    try:
        if hc.timeout is not None:
            await asyncio.wait_for(hc.check(), hc.timeout)
        else:
            await hc.check()
    except asyncio.TimeoutError:
        healthy = False
        results.append(CheckResult(name=hc.name, status="error", error=f"timed out after {hc.timeout}s"))
    except Exception as exc:  # existing broad catch — surfaced as a check error
        healthy = False
        results.append(CheckResult(name=hc.name, status="error", error=str(exc)))
    else:
        results.append(CheckResult(name=hc.name, status="ok"))
```

- The `asyncio.TimeoutError` handler MUST precede the generic `except Exception` (broad catch would
  otherwise swallow the timeout with an empty `str(exc)`).
- `asyncio.TimeoutError` is an alias of builtin `TimeoutError` on 3.11+ and importable on 3.10 — catch it.
- **Acceptance:** Task 1 tests pass (Green); mypy + pyright strict clean; `timeout=None` path unchanged.

### [x] Task 3 — Docstrings + full verify gate (`litestar-batteries-8lt.3`) [65c0f83] — depends on Task 2

- Document the `timeout` field on `HealthCheck` (seconds; `None` = no timeout).
- Adjust the "checks run sequentially" comment in `controller.py:39-40` if warranted.
- Run the full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest` — coverage ≥ 80%.
- **Acceptance:** full gate green; coverage ≥ 80%; docstring documents timeout semantics.

## Notes / Gotchas

- `HealthCheck` is `@dataclass(frozen=True)`; a new field with a default is fine (all existing fields
  are positional/defaulted-safe — `name`, `check` have no defaults, `timeout` does, so ordering holds).
- Do **not** add a global `HealthConfig.check_timeout` (explicitly out of scope per locked decision).

> **Post-review correction (PR #8, `litestar-batteries-8lt.4`).** The originally-shipped `asyncio.wait_for`
> approach (Task 2 snippet above) had a defect: `wait_for` raises `asyncio.TimeoutError` for its deadline,
> but a check raising its *own* `asyncio.TimeoutError` surfaces as the same type, so `except asyncio.TimeoutError`
> mislabeled it as the wrapper deadline (`"timed out after Nones"` on the `timeout=None` path). Final fix keeps
> `asyncio.wait_for` (so caller cancellation still cancels the check — no orphaned task) and disambiguates via a
> `_guarded` wrapper that re-types the check's *own* `asyncio.TimeoutError` as a private `_CheckFailed` (message
> preserved); a bare `asyncio.TimeoutError` out of `wait_for` then means only the deadline (`_DeadlineExceeded`).
> An interim task-based `asyncio.wait` variant was rejected in review because it orphaned the check on caller
> cancellation. See `controller.py` and `patterns.md`.

## Definition of Done

- [x] All 3 tasks closed in Beads with commit references. [65c0f83]
- [x] `GET /health/ready` returns `503` (not a hang) when a check exceeds its `timeout`.
- [x] `timeout=None` checks behave exactly as before.
- [x] Full gate green, coverage ≥ 80% (10 passed, 100% coverage).

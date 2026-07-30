# litestar-batteries

Batteries-included utilities for [Litestar](https://litestar.dev) — reusable, first-party-flavored
plugins that cut the boilerplate you'd otherwise re-write on every production service.

Fully typed (ships `py.typed`), targets **Litestar 2.x** on **Python 3.10+**, and leans on the
standard library plus deliberate, documented dependencies.

## Install

```bash
uv add litestar-batteries
```

<sub>(or `pip install litestar-batteries`)</sub>

## Batteries

### Health check

A drop-in liveness/readiness plugin. Register `HealthPlugin` and you get two endpoints:

| Endpoint | Meaning | Response |
|----------|---------|----------|
| `GET /health` | **Liveness** — the process is up | always `200 {"status": "ok", "checks": []}` |
| `GET /health/ready` | **Readiness** — dependencies are usable | `200` if every check passes, `503` if any fails |

```python
from litestar import Litestar

from litestar_batteries import HealthCheck, HealthConfig, HealthPlugin


async def db_ready() -> None:
    # Raise to signal "not ready"; return normally to signal "ready".
    await database.execute("SELECT 1")


app = Litestar(
    plugins=[
        HealthPlugin(
            HealthConfig(checks=[HealthCheck("db", db_ready)]),
        )
    ]
)
```

A readiness check is an `async () -> None` callable that **raises on failure**. Each check's outcome
is reported per-name; a raised exception becomes a `CheckResult` error and flips the overall response
to `503`:

```json
{
  "status": "error",
  "checks": [
    {"name": "db", "status": "error", "error": "connection refused"}
  ]
}
```

#### Per-check timeout

By default a check awaits without a time limit. Set `timeout` (seconds) on a `HealthCheck` to bound it,
so a stalled dependency fails fast as `503` instead of hanging `/health/ready`:

```python
HealthConfig(
    checks=[
        HealthCheck("db", db_ready, timeout=5.0),   # 503 if it takes > 5s
        HealthCheck("cache", cache_ready),          # timeout=None (default) → unbounded
    ]
)
```

A timeout surfaces as a check error (`"timed out after 5.0s"`). A `TimeoutError` raised by the check
*itself* (e.g. an upstream client timeout) keeps its own message rather than being reported as the
wrapper's deadline.

#### Configuration

`HealthConfig` fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `path` | `str` | `"/health"` | Base path; readiness is served at `{path}/ready`. |
| `checks` | `Sequence[HealthCheck]` | `()` | Readiness checks, run sequentially in registration order. |

`HealthCheck` fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | `str` | — | Name reported in the readiness result. |
| `check` | `Callable[[], Awaitable[None]]` | — | Async callable; raises on failure. |
| `timeout` | `float \| None` | `None` | Per-check timeout in seconds; `None` = unbounded. |

Change the mount path with `HealthConfig(path="/healthz")`.

## Development

```bash
uv sync                     # install (with the dev group)
uv run pytest               # tests (80% coverage gate)
uv run ruff check .         # lint
uv run ruff format --check .  # format check
uv run mypy                 # type check (strict)
uv run pyright              # type check (strict)
```

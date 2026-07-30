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
    # Probe your real dependency here, e.g. `await db.execute("SELECT 1")`.
    # Raise to signal "not ready"; return normally to signal "ready".
    ...


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

### Idempotency

Deduplicate retried unsafe requests so a client timeout or network retry can't create a
duplicate order/charge. Add `IdempotencyPlugin`; when a request on a configured method carries an
`Idempotency-Key` header, the first response is stored and replayed for subsequent retries.

```python
from litestar import Litestar

from litestar_batteries import IdempotencyConfig, IdempotencyPlugin

app = Litestar(
    route_handlers=[...],
    plugins=[IdempotencyPlugin(IdempotencyConfig())],  # POST + PATCH by default
)
```

A client sends the same key when retrying:

```http
POST /orders HTTP/1.1
Idempotency-Key: 8f3b...c1
```

Behaviour on a configured method carrying the header:

| Situation | Result |
|-----------|--------|
| new key | run the handler, store the response, return it |
| same key + same request body | replay the stored response + `Idempotency-Replayed: true` (handler not re-run) |
| same key + **different** body | `422 Unprocessable Entity` |
| key still in flight | `409 Conflict` |
| no header, or non-configured method | passed through untouched |
| first response was `5xx` | not cached — a retry re-runs the handler |

#### Backing store

State lives in a [Litestar store](https://docs.litestar.dev/2/usage/stores.html) named
`"idempotency"`. By default that's an in-memory store (per-process). Share it across processes by
mapping the name to Redis — **no code change**:

```python
from litestar.stores.redis import RedisStore

app = Litestar(
    route_handlers=[...],
    plugins=[IdempotencyPlugin()],
    stores={"idempotency": RedisStore.with_client(url="redis://localhost:6379")},
)
```

> **Concurrency caveat.** In-flight (`409`) detection is serialized per worker with a lock. The
> Litestar `Store` interface has no atomic check-and-set, so across multiple processes the guard is
> **best-effort** — it narrows, but does not eliminate, the window where two simultaneous first
> requests could both start. For a hard guarantee, back it with a store offering atomic operations.

#### Configuration

`IdempotencyConfig` fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `header_name` | `str` | `"Idempotency-Key"` | Request header carrying the key (matched case-insensitively). |
| `methods` | `Sequence[str]` | `("POST", "PATCH")` | Methods that participate. |
| `store` | `str` | `"idempotency"` | Litestar store registry name. |
| `ttl` | `int` | `86400` | Seconds a completed response stays replayable. |
| `lock_ttl` | `int` | `60` | Seconds the in-flight marker survives (bounds a crashed request). |

## Development

```bash
uv sync                     # install (with the dev group)
uv run pytest               # tests (80% coverage gate)
uv run ruff check .         # lint
uv run ruff format --check .  # format check
uv run mypy                 # type check (strict)
uv run pyright              # type check (strict)
```

## License

[MIT](./LICENSE)

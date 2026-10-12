# litestar-batteries

[![CI](https://github.com/hasansezertasan/litestar-batteries/actions/workflows/ci.yml/badge.svg)](https://github.com/hasansezertasan/litestar-batteries/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/codecov/c/github/hasansezertasan/litestar-batteries)](https://codecov.io/gh/hasansezertasan/litestar-batteries)
[![Documentation Status](https://img.shields.io/github/deployments/hasansezertasan/litestar-batteries/github-pages?label=docs)](https://hasansezertasan.github.io/litestar-batteries)
[![PyPI - Version](https://img.shields.io/pypi/v/litestar-batteries.svg)](https://pypi.org/project/litestar-batteries)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/litestar-batteries.svg)](https://pypi.org/project/litestar-batteries)
[![License - MIT](https://img.shields.io/github/license/hasansezertasan/litestar-batteries.svg)](https://opensource.org/licenses/MIT)
[![GitHub Stars](https://img.shields.io/github/stars/hasansezertasan/litestar-batteries?style=social)](https://github.com/hasansezertasan/litestar-batteries/stargazers)
[![Latest Commit](https://img.shields.io/github/last-commit/hasansezertasan/litestar-batteries)](https://github.com/hasansezertasan/litestar-batteries)

[![Checked with mypy](http://www.mypy-lang.org/static/mypy_badge.svg)](http://mypy-lang.org/)
[![linting - Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/charliermarsh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/hasansezertasan/litestar-batteries/badge)](https://scorecard.dev/viewer/?uri=github.com/hasansezertasan/litestar-batteries)
[![GitHub Tag](https://img.shields.io/github/tag/hasansezertasan/litestar-batteries?include_prereleases=&sort=semver&color=black)](https://github.com/hasansezertasan/litestar-batteries/releases/)

[![Downloads](https://pepy.tech/badge/litestar-batteries)](https://pepy.tech/project/litestar-batteries)
[![Downloads/Month](https://pepy.tech/badge/litestar-batteries/month)](https://pepy.tech/project/litestar-batteries)
[![Downloads/Week](https://pepy.tech/badge/litestar-batteries/week)](https://pepy.tech/project/litestar-batteries)

> Batteries-included utilities for Litestar

-----

## Table of Contents

- [Installation](#installation)
- [Batteries](#batteries)
- [Support](#support-heart)
- [Motivation](#motivation)
- [About](#about)
- [Author](#author-person_with_crown)
- [Analysis](#analysis)
- [Contributing](#contributing-heart)
- [Development](#development-toolbox)
- [Releasing](#releasing)
- [Credits](#credits)
- [License](#license-scroll)
- [Changelog](#changelog-memo)

## Installation

`litestar-batteries` is a library. Add it to your project as a dependency:

```console
uv add litestar-batteries
```

Or with `pip`:

```console
pip install litestar-batteries
```

### Verify the installation

The package root is importable after installation:

```pycon
>>> from litestar_batteries import __doc__
>>> isinstance(__doc__, str)
True

```

## Batteries

Reusable, first-party-flavored plugins that cut the boilerplate you'd otherwise
re-write on every production service. Fully typed (ships `py.typed`), targets
**Litestar 2.x** on **Python 3.10+**, and leans on the standard library plus
deliberate, documented dependencies.

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
    plugins=[HealthPlugin(HealthConfig(checks=[HealthCheck("db", db_ready)]))]
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
        HealthCheck("db", db_ready, timeout=5.0),  # 503 if it takes > 5s
        HealthCheck("cache", cache_ready),  # timeout=None (default) → unbounded
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
| response is not `2xx`/`4xx` (a redirect or `5xx`) | not cached — a retry re-runs the handler |

The request fingerprint covers the query string, raw body bytes, `Content-Type` and
`Content-Encoding`. Reusing a key with different body representation metadata also returns `422`.
After replaying the buffered request body, subsequent ASGI `receive()` calls delegate to the server
so streaming responses can wait for and observe client disconnects.

Only `2xx` and `4xx` responses are cached: they're final and fully replayable from the stored
status + body + content-type. Redirects are skipped (the `Location` header isn't carried), and `5xx`
must stay retryable.
`426 Upgrade Required` is also skipped: its required hop-by-hop `Upgrade` header is not replayed.
Responses declaring ASGI trailers are served but not cached, so a retry retains their full metadata.
If delivery or task cancellation interrupts a completed response, finalization is shielded until the
captured response is persisted. Cancellation before response completion leaves the reservation to
expire, because the handler may already have performed its side effect.

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

> **`lock_ttl` must exceed your slowest handler.** The in-flight marker expires after `lock_ttl`
> seconds (so a crashed request can't wedge a key forever). If a handler runs longer than that, the
> marker expires mid-flight and a concurrent retry will see no record and re-run — raise `lock_ttl`
> above your worst-case handler duration.

##### Cross-process concurrency

By default, in-flight (`409`) detection is serialized per worker with a lock. Litestar's `Store` has
no atomic check-and-set, so **across multiple processes the default guard is best-effort** — it
narrows, but does not eliminate, the window where two simultaneous first requests both start.

For a real cross-process guarantee, pass a `claim` — an `AtomicClaim` whose reservation is atomic.
`RedisAtomicClaim` is provided (duck-typed against `redis.asyncio.Redis`, no hard dependency):

```python
from redis.asyncio import Redis

from litestar_batteries import IdempotencyConfig, IdempotencyPlugin, RedisAtomicClaim

claim = RedisAtomicClaim(Redis.from_url("redis://localhost:6379"))
plugin = IdempotencyPlugin(IdempotencyConfig(claim=claim))
```

When `claim` is set the middleware routes all record I/O through it (via `SET NX`), so the `store`
setting is unused.

Each reservation carries a unique ownership token. Custom `AtomicClaim` backends must implement
`set(key, value, expected=sentinel, ttl=...)` and `delete(key, expected=sentinel)` as atomic
compare-and-set/delete operations, returning whether the expected reservation was still present.
`RedisAtomicClaim` uses Redis Lua scripts for these operations (the client must support `eval`).
An expired owner cannot overwrite or delete a newer reservation or completed response.
This does not renew the lease: keep `lock_ttl` above the handler duration to prevent duplicate execution.

#### Multi-tenant isolation

The store key is namespaced by method + path + key. For a multi-tenant API set `scope` so the same
key from two different callers never collides (which would replay one caller's response to another):

```python
IdempotencyConfig(scope=lambda request: request.headers.get("X-Tenant-Id", ""))
```

#### Errors

`409` (in-flight), `422` (key reused with a different body), and `400` (missing key when
`require_key=True`, or an empty/over-long/non-ASCII key) are returned as RFC 9457
`application/problem+json` with a `type` of `urn:litestar-batteries:idempotency:<slug>`.

#### Configuration

`IdempotencyConfig` fields:

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `header_name` | `str` | `"Idempotency-Key"` | Request header carrying the key (matched case-insensitively). |
| `methods` | `Sequence[str]` | `("POST", "PATCH")` | Methods that participate. |
| `store` | `str` | `"idempotency"` | Litestar store registry name (ignored when `claim` is set). |
| `ttl` | `int` | `86400` | Seconds a completed response stays replayable. |
| `lock_ttl` | `int` | `60` | Seconds the in-flight marker survives; **must exceed your slowest handler** (see caveat). |
| `max_body_bytes` | `int \| None` | `1048576` | Responses larger than this are served but not cached; buffering short-circuits at the cap. `None` disables. |
| `max_request_bytes` | `int \| None` | `10485760` | Request bodies larger than this are rejected with `413` before buffering (matches Litestar's default body limit). `None` disables. |
| `scope` | `Callable[[Request], str] \| None` | `None` | Per-caller key isolation (e.g. tenant id); see above. |
| `require_key` | `bool` | `False` | Reject a configured-method request with no key → `400`. |
| `max_key_length` | `int` | `255` | Reject keys longer than this → `400` (also bounds key-cardinality abuse). |
| `replay_headers` | `frozenset[str]` | see below | Response headers stored & replayed. |
| `claim` | `AtomicClaim \| None` | `None` | Atomic cross-process reservation backend (e.g. `RedisAtomicClaim`). |

`replay_headers` defaults to `content-type`, `content-language`, `content-encoding`, `content-range`, `cache-control`,
`etag`, `expires`, `last-modified`, `location`, `www-authenticate`, `proxy-authenticate`, `allow`,
`retry-after` (protocol headers for cached `401`/`407`/`405`/`429` responses) — volatile/sensitive
headers (`set-cookie`,
`authorization`, hop-by-hop) are intentionally excluded from replays.

## Support :heart:

If you have any questions or need help, feel free to open an issue on the [GitHub repository][litestar-batteries].

## Motivation

Common Litestar needs — health checks, idempotency, cross-cutting utilities — are
re-implemented from scratch on every project. `litestar-batteries` packages
battle-tested, first-party-flavored solutions so teams start further ahead instead
of copy-pasting glue code.

## About

A batteries-included utility collection for [Litestar](https://litestar.dev)
applications: reusable extensions, plugins, and helpers for production services.
It is for Python developers building on Litestar who want opinionated, well-tested
building blocks. Each battery is independent and opt-in; importing one never forces
the others.

## Author :person_with_crown:

This project is maintained by [Hasan Sezer Taşan][author], It's me :wave:

## Analysis

- [Snyk Python Package Health Analysis](https://snyk.io/advisor/python/litestar-batteries)
- [Libraries.io - PyPI](https://libraries.io/pypi/litestar-batteries)
- [Safety DB](https://data.safetycli.com/packages/pypi/litestar-batteries)
- [PePy Download Stats](https://www.pepy.tech/projects/litestar-batteries)
- [PyPI Download Stats](https://pypistats.org/packages/litestar-batteries)
- [Pip Trends Download Stats](https://piptrends.com/package/litestar-batteries)
- [PyPI Map Dependency Graph](https://pypimap.com/package/litestar-batteries)

## Contributing :heart:

Any contributions are welcome! Please follow the [Contributing Guidelines](./.github/CONTRIBUTING.md) to contribute to this project.

## Development :toolbox:

See the [Contributing Guidelines](./.github/CONTRIBUTING.md#your-first-code-contribution)
for local setup, the common development tasks (exposed via [mise](https://mise.jdx.dev)),
building and previewing the documentation, and the VS Code debugging configurations.

## Releasing

Versioning and releases are automated with [release-please](https://github.com/googleapis/release-please), driven by [Conventional Commit](https://www.conventionalcommits.org/en/v1.0.0/) PR titles squash-merged into `main`. release-please maintains a release PR that bumps the version and `CHANGELOG.md`; merging it tags the release and publishes to PyPI. See the [Contributing Guidelines](./.github/CONTRIBUTING.md#releasing) for the commit conventions, and the [Repository setup](./docs/maintaining/setup.rst) guide for one-time configuration and optional post-launch integrations such as a social preview, downstream packaging, and Repology.

Pause merges that change `.github/workflows/`, including Renovate action-pin updates, from merging a release PR until the entire Release run finishes. Workflow differences between the release commit and current `main` can block tag or release creation with a 403 when using `GITHUB_TOKEN`. See [Release recovery](./docs/maintaining/setup.rst#keep-workflow-changes-out-of-an-active-release) for prevention and recovery steps.

For adoption or template-update reconciliation, ask your agent to "audit this
template adoption/update against our existing project behavior".
The shipped [template-adoption skill](./.claude/skills/template-adoption/SKILL.md)
also supports audits after an update was applied. It compares workflow behavior,
required checks, custom tooling, and documentation, and asks before consequential
cleanup. Its prek-workflow example shows why duplicate commands alone do not
justify removing a workflow. Use the sibling `repo-setup` skill for repository
settings and release setup.

## Credits

This package was created with [Copier](https://github.com/copier-org/copier) and the [hasansezertasan/copier-pyproject](https://github.com/hasansezertasan/copier-pyproject) project template.

## License :scroll:

This project is licensed under the [MIT License](./LICENSE).

## Changelog :memo:

For a detailed list of changes, please refer to the [CHANGELOG](./CHANGELOG.md).

<!-- Refs -->
[author]: https://github.com/hasansezertasan
[litestar-batteries]: https://github.com/hasansezertasan/litestar-batteries

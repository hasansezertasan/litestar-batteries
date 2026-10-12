---
type: Guide
title: Architecture
description: Current-state structure of litestar-batteries — package layout, the battery pattern, and each shipped battery.
tags: [architecture, litestar, plugins]
---

# Architecture

Current-state reference for how `litestar-batteries` is structured. Read alongside [patterns/](patterns/index.md).

## What this is

A **library** (no CLI, no `[project.scripts]`) of reusable, first-party-flavored Litestar
utilities ("batteries"). Runtime deps: `litestar>=2,<3`, `msgspec`, and `typing_extensions`
(all direct, justified in `product/tech-stack.md`). `src/` layout,
`litestar_batteries` package, ships `py.typed`. Built with `hatchling` + `hatch-vcs`
(version dynamic, from Git tags).

## Package layout

```text
src/litestar_batteries/
  __init__.py            # re-exports every battery's public API (+ __version__)
  _version_fallback.py   # importlib.metadata version lookup with "0.0.0" fallback
  __main__.py            # template stub: exits non-zero (no runnable component)
  <battery>/
    __init__.py          # the battery's public API (__all__)
    models.py            # msgspec.Struct response types + dataclass config/value types
    controller.py        # build_<x>_controller(config) -> type[Controller]  (factory, kept internal)
    plugin.py            # <X>Plugin(InitPlugin) — the public entry point
    middleware.py        # (middleware batteries) <X>Middleware(ASGIMiddleware)
```

## The battery pattern

Every battery is a **Litestar `InitPlugin`**, established by the health battery:

- **Config object** — a plain `@dataclass` (`<X>Config`) with sensible defaults (e.g. `path="/health"`,
  `checks=()`). Sequence fields use `field(default_factory=tuple)`.
- **Controller factory** — `build_<x>_controller(config) -> type[Controller]` closes over the config
  and returns a `Controller` **subclass** (`path = config.path`, handlers as `@get(...)` methods). The
  factory is internal, not exported.
- **Plugin** — `<X>Plugin(InitPlugin)` takes `config: <X>Config | None = None`; its **synchronous**
  `on_app_init(app_config)` appends the built controller to `app_config.route_handlers` and returns
  the config. This is the only registration path exposed to consumers (plugin-only contract).
- **Public API** — the battery's `__init__` exports the plugin, config, and any response types;
  `litestar_batteries.__init__` re-exports them so consumers do `from litestar_batteries import ...`.

### Responses & wire format

- Response bodies are `msgspec.Struct` types. Handlers that return a fixed shape annotate it directly
  (`-> HealthReport`); handlers that need a **runtime-chosen status code** return
  `Response[T](content, status_code=...)`.
- Litestar cannot infer dynamically-set status codes for the OpenAPI schema. Declare them explicitly on
  the decorator: `@get("/ready", responses={HTTP_503_...: ResponseSpec(data_container=HealthReport, description=...)})`.
- Enum-like string fields use `Literal[...]` (e.g. `Status = Literal["ok", "error"]`) so the schema
  renders a real enum and typos are caught under strict typing.

## The health battery (reference implementation)

`litestar_batteries.health` — `HealthPlugin(HealthConfig(path="/health", checks=[HealthCheck(name, coro)]))`.

- `GET {path}` (liveness): always `200`, `HealthReport(status="ok")` — process is up.
- `GET {path}/ready` (readiness): awaits each `HealthCheck.check` (an async `() -> None` that raises on
  failure) **sequentially in registration order**; aggregates per-check `CheckResult`s; returns `200`
  if all pass, `503` if any raised. `except Exception` converts a failure to a per-check error —
  `BaseException` (incl. `CancelledError`) still propagates. Sequential execution is a documented
  contract; batteries needing concurrency should aggregate upstream.
- **Per-check timeout:** `HealthCheck.timeout: float | None = None` (opt-in; `None` = unbounded, the
  default, so existing configs are unchanged). When set, the check runs under `asyncio.wait_for`; on the
  deadline the check is cancelled and the wrapper reports a `CheckResult` error (`"timed out after {t}s"`)
  → `503`, so a stalled dependency can no longer hang the endpoint. To keep the deadline distinct from a
  check that raises its *own* `asyncio.TimeoutError` (same exception type), the check is awaited through a
  `_guarded` wrapper that re-types the check's own timeout as a private `_CheckFailedError` (message
  preserved) — so a bare `asyncio.TimeoutError` out of `wait_for` unambiguously means the deadline, and
  the check's real error is never mislabeled. Using `wait_for` (rather than a hand-rolled task +
  `asyncio.wait`) also means the check is cancelled on caller cancellation and never orphaned. The
  per-check try/except lives in `_evaluate_check` (returning a `CheckResult`, never raising), so the
  readiness handler stays a flat sequential loop.
- Public types: `HealthPlugin`, `HealthConfig`, `HealthCheck`, `HealthReport`, `CheckResult`.

## The idempotency battery

`litestar_batteries.idempotency` — `IdempotencyPlugin(IdempotencyConfig())` dedupes retried unsafe
requests by an `Idempotency-Key` header, following
[draft-ietf-httpapi-idempotency-key-header](https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-07).
It is a middleware battery: `on_app_init` appends an `IdempotencyMiddleware(ASGIMiddleware)` **instance**
directly to `app_config.middleware` (no `DefineMiddleware` wrapper needed on Litestar 2.x).
`handle` is a thin orchestrator over staged helpers — `_resolve_key` (key validation/passthrough),
`_prepare_body` (buffering + size/disconnect handling), `_acquire` (claim/store reservation),
`_serve_existing` (409/422/replay) — with response capture/finalization in `_Capture` /
`_CaptureSession` and ownership-guarded writes in `_RecordWriter`.

| Situation (configured method + key) | Result |
|-------------------------------------|--------|
| new key | run handler; persist the complete response; return it |
| same key, done, same request fingerprint | replay stored status + allow-listed headers + body, with `Idempotency-Replayed: true`; handler not re-run |
| same key, done, different fingerprint | `422` problem+json |
| same key, in flight | `409` problem+json |
| no key / non-configured method | pass through (or `400` when `require_key=True`); an explicitly empty or invalid key is always `400` |
| `5xx`, `3xx`, `426`, trailers, incomplete or oversized response | not cached — a retry re-runs the handler |

- **Config** (`IdempotencyConfig`): `header_name`, `methods=("POST","PATCH")`, `store="idempotency"`
  (Litestar `Store` registry name; `MemoryStore` default, Redis via `stores=`), `ttl=86400`,
  `lock_ttl=60`, `max_body_bytes` (1 MiB response cap), `max_request_bytes` (10 MiB request cap),
  `scope` (callable → tenant isolation), `require_key`, `max_key_length=255`, `replay_headers`
  (allow-list; never `Set-Cookie`/`Authorization`), `claim` (`AtomicClaim`).
- **Store key** is length-delimited `{method}:{len(path)}:{path}:…` plus the optional scope, so `:` in a
  path or key can't collide two entries.
- **Fingerprint** = SHA-256 over length-framed query bytes, `Content-Type`, `Content-Encoding`, and the
  raw body, fed incrementally.
- **Records** (`StoredResponse`, msgpack-encoded) carry `state` (`processing`/`done`), status,
  headers, body, request hash, and an **owner token** that fences stale owners.
- **Claims:** default is a per-worker `asyncio.Lock` around get→set-sentinel (cross-process
  best-effort, since the `Store` ABC has no atomic CAS). `RedisAtomicClaim` (opt-in, `SET NX` + Lua
  compare-and-set/delete) gives a real cross-process claim; custom `AtomicClaim.set`/`delete` take
  `expected` bytes and return success.
- **`lock_ttl` must exceed the slowest handler** — lease renewal is not implemented.
- **Request buffering** checks prospective size before copying a chunk; after replaying buffered events
  the middleware delegates to the server's original `receive()` (so disconnect watchers block and see
  `http.disconnect`). Client disconnect while buffering skips persistence.
- **Cancellation:** `CancelledError` is caught explicitly; finalization is shielded in a strongly
  referenced task, then cancellation propagates. A complete captured response is still persisted;
  an in-flight marker is retained if cancelled before completion.
- Errors are RFC 9457 problem+json with `urn:litestar-batteries:idempotency:*` types.
- Public types: `IdempotencyPlugin`, `IdempotencyConfig`, `AtomicClaim`, `RedisAtomicClaim`.
- Deferred: HMAC fingerprint, lease renewal, metrics, per-route `no-store` opt-out.

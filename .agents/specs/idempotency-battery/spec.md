# Spec: idempotency-battery

> Beads epic: `litestar-batteries-va8`. Beads is the source of truth for task status — do **not**
> hand-edit checkboxes; sync from Beads. High-Definition Worksheet: implementable with zero prior
> context. Grounded on Litestar 2.x `ASGIMiddleware` + `Store` APIs (verified via docs 2026-07-31).

## Problem

Retried unsafe requests (client timeout, network retry, at-least-once delivery) execute twice —
duplicate orders/charges. Litestar ships no idempotency support (verified 2026-07-31: not native, not
`contrib`, no community plugin). This battery dedupes retried `POST`/`PATCH` requests by an
`Idempotency-Key` header, replaying the first response.

## Goal

```python
from litestar import Litestar
from litestar_batteries import IdempotencyConfig, IdempotencyPlugin

app = Litestar(
    route_handlers=[...],
    plugins=[IdempotencyPlugin(IdempotencyConfig())],   # defaults: POST+PATCH, header "Idempotency-Key"
    # optional redis backing: stores={"idempotency": RedisStore.with_client(url=...)}
)
```

Behaviour on a configured method carrying `Idempotency-Key: <k>`:

| Situation | Result |
|-----------|--------|
| new key | run handler; store the response; return it |
| same key, **done**, same request body | replay stored `status`+`body`+`content-type` + `Idempotency-Replayed: true`; handler **not** re-run |
| same key, **done**, **different** request body | `422 Unprocessable Entity` (key reused with a different payload) |
| same key, still **in-progress** | `409 Conflict` |
| no key, or non-configured method (e.g. `GET`) | pass through untouched |
| first response was `5xx` | not cached — a retry re-runs the handler |

## Decisions (locked)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| v1 scope | **Full**: cache+replay **+** in-flight `409` **+** body-fingerprint `422` | Only this is actually safe under concurrent retries; matches Stripe/IETF. |
| Methods (default) | **`POST` + `PATCH`** (configurable) | The non-idempotent methods; `PUT`/`DELETE` are already idempotent by HTTP semantics. |
| Trigger | **Client-driven** — dedupe when header present, else pass through | Industry norm; backward-compatible, non-intrusive. |
| Header | `Idempotency-Key` (configurable) | Convention. |
| Backend | Litestar **Store** by registry name `"idempotency"` (default `MemoryStore`) | Redis is a config swap (`stores={"idempotency": RedisStore(...)}`), no code change. |
| Key scoping | namespaced **`{method}:{path}:{key}`** | Same key on different endpoints must not collide. |
| Cached responses | `2xx` and `4xx` (final); **never `5xx`** | Failures must be retryable; final client/success outcomes are stable. |
| Replayed state | `status` + body + `content-type` only (+ marker header) | Replaying `Set-Cookie`/`Date`/etc. would be wrong. |
| Record encoding | `msgspec.msgpack` (already a dep) | Stores hold `bytes`; msgpack handles `bytes` bodies natively. |
| TTL | default `86400`s (24h), configurable | Standard idempotency window. |

## Grounded API facts (Litestar 2.x)

- Middleware: `from litestar.middleware import ASGIMiddleware`; `async def handle(self, scope, receive, send, next_app) -> None`. Restrict with `scopes = (ScopeType.HTTP,)` (`from litestar.enums import ScopeType`). Call `await next_app(scope, receive, send)`.
- Read request: `Request(scope)` → `.method`, `.headers`; path via `scope["path"]`.
- Capture response: wrap `send`; on `message["type"] == "http.response.start"` read `message["status"]` and headers via `MutableScopeHeaders.from_message(message)` (`from litestar.datastructures import MutableScopeHeaders`); on `"http.response.body"` accumulate `message["body"]` while `message.get("more_body")`.
- Buffer request body: consume `receive()` `http.request` messages (respecting `more_body`), then hand `next_app` a replay `receive` that yields the buffered messages.
- Store: `scope["app"].stores.get("idempotency")` → `Store` with `await get(key) -> bytes | None`, `await set(key, value, expires_in=<seconds>)`, `await delete(key)`.
- **Verify at implement time:** how `InitPlugin` registers an `ASGIMiddleware` instance — `app_config.middleware.append(instance)` vs wrapping in `DefineMiddleware` — against the installed litestar (mirror the health battery's "confirm `on_app_init` is sync" check).

## Known limitation (document in code + README)

The `Store` ABC has no atomic check-and-set, so the get→set that sets the in-flight sentinel has a race
window: two truly-simultaneous first requests can both miss the sentinel and both execute. The `409`
lock therefore **narrows** the duplicate window but is **best-effort**, not a distributed lock. Callers
needing a hard guarantee should back it with a store offering atomic ops. State this plainly.

## Target layout

```
src/litestar_batteries/
  __init__.py            # + re-export IdempotencyPlugin, IdempotencyConfig
  idempotency/
    __init__.py          # public exports
    models.py            # IdempotencyConfig, _StoredResponse (msgspec.Struct)
    middleware.py        # IdempotencyMiddleware(ASGIMiddleware)
    plugin.py            # IdempotencyPlugin(InitPlugin)
```

## Tasks

### [ ] Task 1 — models, config, plugin scaffold + exports (`litestar-batteries-va8.1`)

- `models.py`: `IdempotencyConfig` dataclass (`header_name="Idempotency-Key"`, `methods=("POST","PATCH")`, `store="idempotency"`, `ttl=86400.0`, `lock_ttl=<small default>`); `_StoredResponse(msgspec.Struct)` with `state: Literal["processing","done"]`, `status: int`, `media_type: str | None`, `body: bytes`, `request_hash: str`.
- `plugin.py`: `IdempotencyPlugin(InitPlugin)` scaffold (`__init__(config=None)`); `on_app_init` wired in T3/T4.
- `__init__.py` exports; re-export from `litestar_batteries.__init__`.
- **Acceptance:** imports cleanly; mypy/pyright strict pass; no behavior yet.

### [ ] Task 2 — TDD failing tests (`litestar-batteries-va8.2`) — depends on Task 1

`tests/test_idempotency.py` (write BEFORE middleware → Red). Cover the behaviour table:
passthrough (no key / `GET`); first request stores + returns; replay (same key+body) with marker header
and handler-not-re-run (assert via a call counter); `422` on same key + different body; `409` on
concurrent in-flight (block the handler on an `asyncio.Event`, drive with `AsyncTestClient`); `5xx`
not cached (retry re-runs); custom `header_name`/`methods`; redis-swap smoke (map `stores={"idempotency": MemoryStore()}`).
- **Acceptance:** tests fail before impl (Red).

### [ ] Task 3 — implement the ASGI middleware (`litestar-batteries-va8.3`) — depends on Task 2

`middleware.py` per "Grounded API facts": method/key gate → passthrough; buffer body + `sha256` hash +
replay receive; store lookup (`done` → 422-on-mismatch / replay; `processing` → 409); else set sentinel
→ run with capturing `send`-wrapper → store `done` (`<500`) or delete sentinel (`>=500`/exception).
Document the best-effort-lock limitation in a comment.
- **Acceptance:** all Task 2 tests pass (Green); mypy/pyright strict clean.

### [ ] Task 4 — wire plugin, README docs, full gate (`litestar-batteries-va8.4`) — depends on Task 3

- Verify the `ASGIMiddleware`-registration mechanism, wire it in `on_app_init`.
- README battery section (usage, config table, redis swap, 409/422 semantics, best-effort caveat); docstrings.
- Full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pyright && uv run pytest` (coverage ≥ 80%).
- **Acceptance:** end-to-end plugin works; full gate green, coverage ≥ 80%.

## Definition of Done

- [ ] All 4 tasks closed in Beads with commit references.
- [ ] Retried `POST`/`PATCH` with a repeated `Idempotency-Key` replays the first response; `409`/`422`/`5xx` behave per the table.
- [ ] Redis backing works via `stores=` with no code change.
- [ ] Full gate green, coverage ≥ 80%; README documents the battery incl. the best-effort-lock caveat.

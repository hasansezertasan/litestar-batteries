# Learnings: idempotency-battery

> Ralph-style running notes. Synced from Beads notes via `/flow:sync`.

## Task 1 — scaffold (`va8.1`) [e79a9e8]

- Verified on litestar 2.24: `ASGIMiddleware.handle(self, scope, receive, send, next_app)`;
  `Store.get(key, renew_for)` / `Store.set(key, value, expires_in)`; an `ASGIMiddleware` **instance**
  appends directly to `app_config.middleware` (no `DefineMiddleware` wrapper) — so `on_app_init` was
  wired in T1 and T4 reduced to README/gate.

## Task 2/3 — tests + middleware (`va8.2`, `va8.3`) [cf3e7db]

- Litestar `POST` returns **201** by default — assert `201`, not `200` (initial test bug).
- Testing true in-flight concurrency through `AsyncTestClient` was nondeterministic (the second
  request may observe a `done` record and replay `201` instead of `409`, depending on interleaving).
  Switched to a **deterministic** test that seeds the exact in-flight sentinel a concurrent request
  would leave, then asserts `409`. A per-worker `asyncio.Lock` serializes the get→set-sentinel window.
- `MemoryStore` get/set do not yield, but the body-buffering `await receive()` does — hence the lock.
  Cross-process dedupe stays best-effort (the `Store` ABC has no atomic CAS).
- Capture the response content-type by scanning the raw `http.response.start` headers, not
  `MutableScopeHeaders.get` (pyright flags its return as partially-unknown under strict).
- `_buffer_request` reassembles chunked bodies and hands the app a replay `receive`; unit-tested
  directly (chunked + disconnect). Relaxed pyright `reportPrivateUsage` under `tests/` for that
  white-box import.

## Task 4 — docs + gate (`va8.4`) [a787106]

- README battery section (behaviour table, Redis swap via `stores=`, best-effort caveat, config table).
- Full gate green: ruff, format, mypy strict, pyright strict (0), pytest **22 passed, 98% coverage**.

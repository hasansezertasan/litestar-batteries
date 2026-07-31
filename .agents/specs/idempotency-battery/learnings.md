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

## PR #12 review follow-up

Triaged 7 threads (Codex + CodeRabbit); 6 valid, 1 skipped:
- **Cache only 2xx/4xx** (was `<500`): 3xx redirects aren't replayable (`_replay` drops `Location`) and a
  disconnected/never-responding handler's `status==0` must not be stored. (Codex + CodeRabbit disconnect thread.)
- **`store_key` length-delimited** to kill the `:`-injection collision (`/orders:v2`+`x` vs `/orders`+`v2:x`). (Codex)
- **`max_body_bytes`** (default 1 MiB) caps cached response size → bounds MemoryStore growth. (CodeRabbit security)
- **`lock_ttl` caveat** documented: must exceed slowest handler or a long-running request's lease expires and a
  retry re-runs; renewable leases deferred (out of v1 scope). (CodeRabbit critical → documented trade-off.)
- **Disconnect bypass**: `_buffer_request` returns a disconnect flag; middleware skips persistence.
- **Pyright `reportPrivateUsage`**: narrowed to an inline `# pyright: ignore` at the import site instead of
  relaxing the rule for all of `tests/`. (CodeRabbit)
- **Skipped**: "future-dated timestamps" — today *is* 2026-07-31 (clock advanced mid-session); CodeRabbit's
  context was stale, timestamps are correct.
- Gate after fixes: **25 passed, 98% coverage**.

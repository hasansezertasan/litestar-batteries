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
- **Skipped**: "future-dated timestamps" — the work ran on 2026-07-31, so the timestamps were correct;
  CodeRabbit's context was stale.
- Gate after fixes: **25 passed, 98% coverage**.

## Prior-art comparison (surveyed 2026-08-06)

Compared our battery against the authoritative spec and 8 libraries to find patterns to adopt.

**Authoritative sources**
- IETF draft — *The Idempotency-Key HTTP Header Field*, `draft-ietf-httpapi-idempotency-key-header-07` (Oct 2025): <https://datatracker.ietf.org/doc/html/draft-ietf-httpapi-idempotency-key-header-07>. Normative: first request → normal; same key + same body → replay; same key + **different** body → **422**; concurrent/in-flight → **409**; missing required key → **400**. Key = Structured-Field quoted string, ≤255, UUIDv4 recommended; errors as RFC 9457 problem+json; no standard "replayed" header.
- Stripe idempotency: <https://docs.stripe.com/api/idempotent_requests> (per-account, all POST, 24h TTL, stores status+body incl. errors, same-key-different-params → error).

**Libraries reviewed**

| Lib | Link | Shape | Fingerprint→mismatch | In-flight | Notable |
|-----|------|-------|----------------------|-----------|---------|
| snok/asgi-idempotency-header | <https://github.com/snok/asgi-idempotency-header> | ASGI mw (Starlette) | ❌ none | `SADD` → 409 | no lock TTL (stranded on crash); drops headers; caches any status |
| mohit (fork) | <https://github.com/mohit-eparchi/asgi-idempotency-header> | ASGI mw | ❌ none | set → 409 | fork adds `method:path:key` namespacing, `redis.asyncio` |
| idemptx | <https://github.com/pypy-riley/idemptx> | FastAPI decorator | ✅ but hashes **all headers** (false 409s) | `SET NX EX` + wait-poll | sync/async backend polymorphism; single TTL for lock+cache |
| relier | <https://github.com/getrelier/relier> | Celery decorator (not HTTP) | key = arg-hash | atomic Lua claim, **prefix-tagged sentinel**, compare-and-delete release | `inflight_ttl > timeout + buffer` enforced at startup; fencing tokens |
| **idemkit** | <https://github.com/idemkit/idemkit> | **formal RFC-2119 spec** + impl | ✅ **422** (fingerprint ≠ key) | subscribe+wait → **423**; `claim_token` fencing, `renew()` lease | single-record state machine; header allow/deny; length-prefixed SHA-256; RFC 9457 `urn:` errors; 5xx never cached |
| carvalho/fastapi-idempotency | <https://github.com/carvalhocaio/fastapi-idempotency> | in-handler demo | ❌ none | ❌ none (TOCTOU race) | teaching demo; unbounded dict |
| **ronango/fastapi-idempotency** | <https://github.com/ronango/fastapi-idempotency> | raw-ASGI mw | ✅ **422**, HMAC length-prefixed | atomic Lua `acquire` (4-way outcome) → **409** | two-phase TTL, `413` size cap, streaming detect, header denylist, metrics protocol, `SECURITY.md` |
| yoyowallet/django-idempotency-key | <https://github.com/yoyowallet/django-idempotency-key> | Django mw + decorators | ❌ body baked into key | lock → **423** | secure-by-default; fail-loud on mis-ordering; Authorization in hash (tenant scope); **no record TTL**; replay overrides status to 409 |

**Cross-language:** idempot-js (Node, IETF-07 + RFC 9457, 409/422) <https://roderick.dk/posts/2026-04-06-announcing-idempot-js/>; Go idempotency-middleware (`SET NX` → 409) <https://github.com/furkandeveloper/idempotency-middleware>; Rails Idempo (atomic Lua, ≤4MB, `no-store` opt-out, 30s default TTL) <https://github.com/julik/idempo>; Spring idempotent-starter (5xx releases the key) <https://foojay.io/today/idempotent-spring-boot-starter/>.

**Where our battery already leads (IETF-correct where most libs err):** `409`/`422` split, body-fingerprint → 422 (snok/mohit/django/carvalho all miss this), cache only 2xx/4xx & never 5xx, length-delimited store key, `max_body_bytes`, marker header, two-phase TTL. On par with the two best (idemkit, ronango) minus the items below.

**Ranked improvement backlog** (also in the [[idempotency-prior-art]] memory):
1. **Tenant/scope isolation** (security, low effort) — key is `method+path+key` only, so two users with the same key on the same endpoint collide/replay each other. Add a configurable `scope` callable. (django/ronango/idemkit all scope.)
2. **Atomic cross-process claim** — our per-worker `asyncio.Lock` is best-effort across workers; the field uses atomic `SET NX`/Lua. Litestar's `Store` ABC has no atomic CAS → opt-in Redis path or keep documenting best-effort.
3. **Response header allow-list** on replay (Content-\*, Location, ETag, Cache-Control; deny Set-Cookie/Authorization) → also enables safe 3xx replay.
4. **Streaming / oversized short-circuit** — stop buffering past `max_body_bytes`; bypass streaming with an `Idempotency-Replay-Unavailable` marker.
5. **Polish:** RFC 9457 problem+json errors; optional `require_key` → 400; key length/charset validation.
6. **Defer:** HMAC fingerprint, lease renewal/fencing tokens, metrics protocol, per-route `no-store` opt-out.

## Hardening implemented (epic `litestar-batteries-9ke`)

Folded in #1–#5 from the backlog above (on the PR #12 branch):
- **Scope isolation** (`scope: Callable[[Request], str] | None`) folded into a length-delimited `store_key` — fixes the cross-tenant replay leak.
- **Atomic cross-process claim** as an opt-in `AtomicClaim` protocol (new `claims.py`) with a duck-typed `RedisAtomicClaim` (`SET NX`); default keeps the per-worker `asyncio.Lock`. The `Store` ABC's lack of atomic CAS is why this is a separate hook rather than a Store method.
- **Response header allow-list** (`replay_headers`, default Content-\*/Location/ETag/Cache-Control…; denies Set-Cookie/Authorization) — `StoredResponse.media_type` replaced by `headers: list[tuple[str,str]]`.
- **Streaming/oversized short-circuit** — `send_wrapper` stops buffering and drops the partial body once past `max_body_bytes` (memory bound).
- **RFC 9457 problem+json** errors (`urn:litestar-batteries:idempotency:*`) + optional `require_key`→400 + key length/charset validation→400.
- Deferred (unchanged): HMAC fingerprint, lease renewal/fencing, metrics, `no-store` opt-out.
- Gate: **32 passed, 98% coverage**, ruff/mypy/pyright clean.

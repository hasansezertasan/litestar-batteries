---
type: Pattern
title: Async and ASGI Patterns
description: Python 3.11-safe asyncio usage, timeout and cancellation handling, and ASGI middleware event rules.
tags: [async, asgi, python]
---

# Async and ASGI Patterns

- **Python 3.11 is the floor → no 3.12+ stdlib APIs in `src`.** Type checkers pinned to 3.11 won't necessarily flag a 3.12-only runtime call. `asyncio.timeout()` is available (3.11+), and `asyncio.TimeoutError` is an alias of builtin `TimeoutError`.
- **Bounding an await ≠ distinguishing your deadline from the awaited code's own timeout.** A coroutine that raises `asyncio.TimeoutError` itself surfaces as the same type as `wait_for`'s deadline. Await it inside a guard wrapper that re-types its own timeout as a private exception (message preserved); then a bare `asyncio.TimeoutError` out of `wait_for` uniquely means the deadline. Order `except asyncio.TimeoutError` before `except Exception`.
- **Prefer `wait_for` over a hand-rolled task + `asyncio.wait`:** `wait_for` cancels the inner coroutine on both its deadline and caller cancellation; `asyncio.wait` does not, which orphans the task on client disconnect.
- **`asyncio.CancelledError` is a `BaseException`:** `except Exception` won't catch it. Catch it explicitly where cleanup matters; shield finalization in a strongly referenced task, wait through repeated cancellation, then re-raise.
- **ASGI events may omit optional fields** (`headers`, `body`, `more_body`); read them with empty defaults.
- **After replaying buffered request events, delegate to the server's original `receive()`.** Synthesizing endless terminal events breaks disconnect watchers (they never block or see `http.disconnect`) and can hot-loop.
- **Check prospective size before copying a chunk** into any buffer — a server can deliver a chunk larger than the cap in one event.
- **A per-worker `asyncio.Lock` is needed around get→set windows** whenever an `await` (e.g. body buffering) sits between them, even if the store calls themselves don't yield.
- **`before_send` hooks must be `async def`.** Litestar thread-dispatches sync hooks for every ASGI message, body chunks included. Silence ruff `RUF029` with a justified `# noqa`. Filter on `message["type"] == "http.response.start"`; the hook sees every outgoing message type.
- **Route-level ASGI middleware never sees router 404/405**; `before_send` does. Pick `before_send` for anything that must decorate every HTTP response.
- **`MutableScopeHeaders.__setitem__` leaves stale duplicates when 3+ copies of a header exist.** To replace, `del headers[name]` (removes all copies), then `headers.add(name, value)`. `from_message` needs a `headers` key; ASGI makes it optional, so default it first. `scope["scheme"]` is optional (default `http`).

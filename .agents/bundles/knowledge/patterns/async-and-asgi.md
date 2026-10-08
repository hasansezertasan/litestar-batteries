---
type: Pattern
title: Async and ASGI Patterns
description: Python 3.10-safe asyncio usage, timeout and cancellation handling, and ASGI middleware event rules.
tags: [async, asgi, python]
---

# Async and ASGI Patterns

- **Python 3.10 is in the CI matrix → no 3.11+ stdlib APIs in `src`.** Typers pinned to 3.10 won't necessarily flag a 3.11-only runtime call. Use `asyncio.wait_for`, not the 3.11+ `asyncio.timeout()`. `asyncio.TimeoutError` is a distinct class on 3.10 and an alias of builtin `TimeoutError` on 3.11+.
- **Bounding an await ≠ distinguishing your deadline from the awaited code's own timeout.** A coroutine that raises `asyncio.TimeoutError` itself surfaces as the same type as `wait_for`'s deadline. Await it inside a guard wrapper that re-types its own timeout as a private exception (message preserved); then a bare `asyncio.TimeoutError` out of `wait_for` uniquely means the deadline. Order `except asyncio.TimeoutError` before `except Exception`.
- **Prefer `wait_for` over a hand-rolled task + `asyncio.wait`:** `wait_for` cancels the inner coroutine on both its deadline and caller cancellation; `asyncio.wait` does not, which orphans the task on client disconnect.
- **`asyncio.CancelledError` is a `BaseException`:** `except Exception` won't catch it. Catch it explicitly where cleanup matters; shield finalization in a strongly referenced task, wait through repeated cancellation, then re-raise.
- **ASGI events may omit optional fields** (`headers`, `body`, `more_body`); read them with empty defaults.
- **After replaying buffered request events, delegate to the server's original `receive()`.** Synthesizing endless terminal events breaks disconnect watchers (they never block or see `http.disconnect`) and can hot-loop.
- **Check prospective size before copying a chunk** into any buffer — a server can deliver a chunk larger than the cap in one event.
- **A per-worker `asyncio.Lock` is needed around get→set windows** whenever an `await` (e.g. body buffering) sits between them, even if the store calls themselves don't yield.

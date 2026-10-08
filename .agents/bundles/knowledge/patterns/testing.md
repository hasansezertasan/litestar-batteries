---
type: Pattern
title: Testing Patterns
description: How batteries are tested — Litestar test clients, deterministic concurrency, and regression-first fixes.
tags: [testing, pytest, litestar]
---

# Testing Patterns

- **Handler/plugin tests** use Litestar's sync `create_test_client(route_handlers=[...], plugins=[...])`; assert status codes and JSON body shape.
- **Litestar `POST` handlers return `201` by default** — assert `201`, not `200`.
- **Don't test true concurrency through `AsyncTestClient`** — interleaving is nondeterministic. Seed the exact intermediate state a concurrent request would leave (e.g. the in-flight sentinel) and assert the response deterministically.
- **Every review-found defect gets a regression test that fails before the fix** (Red → Green); include it in the same commit as the fix so each commit stays green.
- **Test strength:** a test for "unbounded by default" must use a slow check, not an instant one, or it can't catch an accidental finite default. Memory-bound claims can be verified with `tracemalloc`.
- Unit-test internal helpers (e.g. request buffering with chunked bodies and disconnects) directly when the public path can't reach an edge case.

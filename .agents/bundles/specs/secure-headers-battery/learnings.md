---
type: Learnings
title: Secure-headers battery learnings
description: Patterns and deferred Minor review findings from the secure-headers-battery flow.
tags: [learnings, security, headers, litestar]
---

# Learnings

## Patterns

- Litestar thread-dispatches **sync** `before_send` hooks (`ensure_async_callable`) for every ASGI message; write them `async def` (silence ruff `RUF029` with a justification) even when they never await.
- `MutableScopeHeaders.__setitem__` leaves stale duplicates when 3+ copies of a header exist; use `del headers[name]` (reverse delete) then `headers.add(...)` to replace.
- Route-level ASGI middleware misses router 404/405; `before_send` covers them. Test those statuses explicitly.
- `frame-ancestors` in CSP overrides `X-Frame-Options` in modern browsers; document the pair together.
- `litestar>=2` lower bound is already wrong repo-wide (`InitPlugin` absent in 2.0.0) - candidate follow-up issue.
- `tox -e style` also runs ty, pyrefly, zuban, pylint, semgrep, slotscheck, vulture; tests need `dict[str, Any]` for `**kwargs` to satisfy ty.

## Deferred Minor findings (quality review at 9aff046, 2026-10-18)

- QR-1 tests: drop redundant tests (`test_app_without_plugin_has_no_security_headers`, `test_hook_override_replaces_handler_header`, one of the two handler-wins tests, duplicated default literals), rename/strengthen the OpenAPI test, group late tests with their peers.
- QR-2 API surface: `SecureHeadersConfig.response_headers()`/`hsts_value()` are public and documented via automodule; consider moving assembly into `hooks.py` as private helpers.
- QR-3 README: vague "looser policy on OpenAPI routes via a handler header" sentence; rewrap the validation paragraph.

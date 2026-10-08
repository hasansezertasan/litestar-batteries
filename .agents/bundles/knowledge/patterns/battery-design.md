---
type: Pattern
title: Battery Design Patterns
description: How batteries are shaped as Litestar plugins and how their responses and models are typed.
tags: [architecture, litestar, plugins]
---

# Battery Design Patterns

- **Battery = Litestar `InitPlugin` + dataclass `*Config`.** The plugin's **sync** `on_app_init(app_config)` registers handlers (`app_config.route_handlers`) or a middleware instance (`app_config.middleware`). Layout: `litestar_batteries/<battery>/{models,plugin}.py` plus `controller.py` or `middleware.py`. Public API re-exported from `litestar_batteries.__init__`. See [architecture](../architecture.md).
- **Plugin-only registration:** controller factories stay internal; consumers only see the plugin, config, and public types.
- **Declare non-inferred status codes** with `responses={code: ResponseSpec(...)}` when a handler sets the status at runtime via `Response(content, status_code=...)`, so they appear in the OpenAPI schema.
- **Enum-like `str` fields use `Literal[...]`** so the schema renders an enum and strict typing catches typos.
- **msgspec empty-literal defaults are per-instance-safe:** `checks: list[X] = []` on a `msgspec.Struct` does not share state (msgspec treats empty `[]`/`{}`/`set()` as implicit factories). Don't "fix" it to `msgspec.field(default_factory=list)` — bare `list` trips pyright strict (`list[Unknown]`). The dataclass mutable-default rule does not apply to Structs.
- **Opt-in, backward-compatible config:** new behavior defaults to off/unbounded (e.g. `HealthCheck.timeout=None`) so existing configs are unchanged.
- **Use Litestar's `Store` registry for state** (`scope["app"].stores.get(name)`), so Redis is a config swap. The `Store` ABC has no atomic CAS: anything needing a real cross-process claim gets a separate opt-in protocol (e.g. `AtomicClaim`) rather than a Store method, and the best-effort default is documented plainly.
- **Survey prior art and the governing spec** (IETF drafts, RFC 9457 for errors) before designing a battery; record deferred items explicitly.
- **Verify external APIs before planning:** confirm current Litestar (or any library) API via docs and the installed version; confirm a pinned action tag exists via `git ls-remote`.

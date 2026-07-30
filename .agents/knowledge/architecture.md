# Architecture

Current-state reference for how `litestar-batteries` is structured. Read alongside `patterns.md`.

## What this is

A **library** (no CLI, no `[project.scripts]`) of reusable, first-party-flavored Litestar
utilities ("batteries"). Runtime deps: `litestar>=2,<3` and `msgspec` (both direct). `src/` layout,
`litestar_batteries` package, ships `py.typed`. Built with `uv_build`.

## Package layout

```
src/litestar_batteries/
  __init__.py            # __version__ (importlib.metadata) + re-exports every battery's public API
  <battery>/
    __init__.py          # the battery's public API (__all__)
    models.py            # msgspec.Struct response types + dataclass config/value types
    controller.py        # build_<x>_controller(config) -> type[Controller]  (factory, kept internal)
    plugin.py            # <X>Plugin(InitPlugin) — the public entry point
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
  default, so existing configs are unchanged). When set, the check runs under `asyncio.wait_for`; a
  timeout surfaces as a `CheckResult` error (`"timed out after {t}s"`) → `503`, so a stalled dependency
  can no longer hang the endpoint. The `except asyncio.TimeoutError` handler precedes the generic
  `except Exception` (order matters — the broad catch would otherwise mask it with an empty message).
- Public types: `HealthPlugin`, `HealthConfig`, `HealthCheck`, `HealthReport`, `CheckResult`.

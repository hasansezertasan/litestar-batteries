# Spec: health-battery (first battery)

> Beads epic: `litestar-batteries-2tg`. Beads is the source of truth for task status — do **not**
> hand-edit checkboxes; sync from Beads. High-Definition Worksheet: implementable with zero prior
> context. Grounded on **Litestar v2.24** docs (verified via Context7 2026-07-23).

## Goal

A drop-in Litestar health check, shipped as a **plugin**:

```python
from litestar import Litestar
from litestar_batteries import HealthPlugin, HealthConfig, HealthCheck

async def db_ready() -> None:
    ...  # raise to signal not-ready

app = Litestar(plugins=[HealthPlugin(HealthConfig(checks=[HealthCheck("db", db_ready)]))])
```

- `GET /health` (liveness) → always `200 {"status": "ok", "checks": []}` (process is up).
- `GET /health/ready` (readiness) → runs each async check; `200` if all pass, `503` if any raise,
  with per-check results. Path prefix is configurable (default `/health`).

## Decisions (locked)

| Decision | Choice |
|----------|--------|
| Registration | **Litestar plugin** (`HealthPlugin` + `HealthConfig`) |
| Readiness check | **async-only** callable `() -> None`, raises on failure |
| litestar pin | `litestar>=2,<3` |
| Serialization | `msgspec.Struct` (ships with litestar) |
| Tests | sync `litestar.testing.create_test_client` (no async-test plugin) |

## Grounded API facts (Litestar 2.24)

- `from litestar import Controller, get` — `Controller` has a `path` class attr; handlers are `@get(...)`.
- Dynamic status: return `Response[T](content, status_code=...)` from `litestar.response`.
- `from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE`.
- Plugin: `from litestar.plugins import InitPlugin`; implement `on_app_init(self, app_config: AppConfig) -> AppConfig` and `app_config.route_handlers.append(controller)`.
- Tests: `from litestar.testing import create_test_client`; `create_test_client(route_handlers=[], plugins=[HealthPlugin(...)])` as a sync context manager.

## Target layout

```
src/litestar_batteries/
  __init__.py          # + re-export health public API (keep __version__)
  health/
    __init__.py        # public exports
    models.py          # CheckResult, HealthReport, HealthCheck, HealthConfig
    controller.py      # _build_controller(config) -> type[Controller]
    plugin.py          # HealthPlugin(InitPlugin)
```

## Tasks

### [x] Task 1 — Add litestar dependency + health subpackage skeleton (`2tg.1`)

- In `pyproject.toml`, set `dependencies = ["litestar>=2,<3"]`. Run `uv sync`.
- Create `src/litestar_batteries/health/__init__.py` (empty for now).
- **Acceptance:** `uv run python -c "import litestar; print(litestar.__version__)"` works; `uv sync` clean.

### [x] Task 2 — Define public types (`2tg.2`) — depends on Task 1

`src/litestar_batteries/health/models.py`:

```python
"""Data types for the health-check battery."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field

import msgspec


class CheckResult(msgspec.Struct):
    """Outcome of a single readiness check."""

    name: str
    status: str  # "ok" | "error"
    error: str | None = None


class HealthReport(msgspec.Struct):
    """Aggregate health/readiness report."""

    status: str  # "ok" | "error"
    checks: list[CheckResult] = []


@dataclass(frozen=True)
class HealthCheck:
    """A named async readiness check that raises on failure."""

    name: str
    check: Callable[[], Awaitable[None]]


@dataclass
class HealthConfig:
    """Configuration for the health plugin."""

    path: str = "/health"
    checks: Sequence[HealthCheck] = field(default_factory=tuple)
```

- **Acceptance:** imports cleanly; mypy/pyright strict pass on this file.

### [x] Task 3 — TDD: failing tests (`2tg.3`) — depends on Task 2

`tests/test_health.py` (write BEFORE controller/plugin exist → Red):

```python
"""Tests for the health-check battery."""

from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE
from litestar.testing import create_test_client

from litestar_batteries import HealthCheck, HealthConfig, HealthPlugin


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise RuntimeError("db down")


def test_liveness_always_ok() -> None:
    with create_test_client(route_handlers=[], plugins=[HealthPlugin()]) as client:
        resp = client.get("/health")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_readiness_all_pass() -> None:
    config = HealthConfig(checks=[HealthCheck("a", _ok), HealthCheck("b", _ok)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        body = resp.json()
        assert body["status"] == "ok"
        assert {c["name"]: c["status"] for c in body["checks"]} == {"a": "ok", "b": "ok"}


def test_readiness_one_fails_returns_503() -> None:
    config = HealthConfig(checks=[HealthCheck("a", _ok), HealthCheck("db", _fail)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_503_SERVICE_UNAVAILABLE
        body = resp.json()
        assert body["status"] == "error"
        db = next(c for c in body["checks"] if c["name"] == "db")
        assert db["status"] == "error"
        assert "db down" in db["error"]


def test_readiness_no_checks_ok() -> None:
    with create_test_client(route_handlers=[], plugins=[HealthPlugin()]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_custom_path() -> None:
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(HealthConfig(path="/healthz"))]) as client:
        assert client.get("/healthz").status_code == HTTP_200_OK
```

- **Acceptance:** `uv run pytest` fails at import/collection (no `HealthPlugin` yet) — confirm Red.

### [x] Task 4 — Implement controller + plugin (Green) (`2tg.4`) — depends on Task 3

`src/litestar_batteries/health/controller.py`:

```python
"""Health-check controller factory."""

from __future__ import annotations

from litestar import Controller, get
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from litestar_batteries.health.models import CheckResult, HealthConfig, HealthReport


def build_health_controller(config: HealthConfig) -> type[Controller]:
    """Build a Controller subclass configured from ``config``."""

    checks = tuple(config.checks)

    class HealthController(Controller):
        path = config.path

        @get()
        async def liveness(self) -> HealthReport:
            return HealthReport(status="ok")

        @get("/ready")
        async def readiness(self) -> Response[HealthReport]:
            results: list[CheckResult] = []
            healthy = True
            for hc in checks:
                try:
                    await hc.check()
                except Exception as exc:  # noqa: BLE001 - surfaced as check error
                    healthy = False
                    results.append(CheckResult(name=hc.name, status="error", error=str(exc)))
                else:
                    results.append(CheckResult(name=hc.name, status="ok"))
            report = HealthReport(status="ok" if healthy else "error", checks=results)
            return Response(report, status_code=HTTP_200_OK if healthy else HTTP_503_SERVICE_UNAVAILABLE)

    return HealthController
```

`src/litestar_batteries/health/plugin.py`:

```python
"""Litestar plugin for the health-check battery."""

from __future__ import annotations

from litestar.config.app import AppConfig
from litestar.plugins import InitPlugin

from litestar_batteries.health.controller import build_health_controller
from litestar_batteries.health.models import HealthConfig


class HealthPlugin(InitPlugin):
    """Registers health/readiness endpoints on the app."""

    def __init__(self, config: HealthConfig | None = None) -> None:
        self.config = config or HealthConfig()

    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        app_config.route_handlers.append(build_health_controller(self.config))
        return app_config
```

- **VERIFY:** confirm `InitPlugin.on_app_init` is **sync** in the installed litestar
  (`uv run python -c "import inspect, litestar.plugins as p; print(inspect.iscoroutinefunction(p.InitPlugin.on_app_init))"` → expect `False`). If it's async, make the method `async def`.
- If `ruff` lacks the `BLE` rule the `# noqa: BLE001` is harmless; keep the broad catch (intentional).
- **Acceptance:** all Task 3 tests pass.

### [x] Task 5 — Public exports + full gate + docs (`2tg.5`) — depends on Task 4

`src/litestar_batteries/health/__init__.py`:

```python
"""Health-check battery public API."""

from litestar_batteries.health.models import CheckResult, HealthCheck, HealthConfig, HealthReport
from litestar_batteries.health.plugin import HealthPlugin

__all__ = ["CheckResult", "HealthCheck", "HealthConfig", "HealthPlugin", "HealthReport"]
```

Re-export from `src/litestar_batteries/__init__.py` (keep the existing `__version__` block), adding:

```python
from litestar_batteries.health import (
    CheckResult,
    HealthCheck,
    HealthConfig,
    HealthPlugin,
    HealthReport,
)

__all__ = [
    "CheckResult",
    "HealthCheck",
    "HealthConfig",
    "HealthPlugin",
    "HealthReport",
    "__version__",
]
```

- Run the full gate: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pyright && uv run pytest`. Fix until green, coverage ≥ 80%.
- Update `.agents/tech-stack.md`: litestar is now a runtime dependency; Litestar `TestClient` is in use.
- **Acceptance:** full gate green, coverage ≥ 80%.

## Notes / Gotchas

- msgspec `Struct` with a mutable default (`checks: list[CheckResult] = []`) is safe — msgspec treats
  it as a per-instance default factory, unlike dataclasses.
- `HealthConfig.checks` uses `field(default_factory=tuple)` (dataclass mutable-default rule).
- Do not serialize `HealthCheck`/`HealthConfig` — they're config, never returned in a response.
- Keep coverage source = `litestar_batteries`; litestar's own code is excluded.

## Definition of Done

- [x] All 5 tasks closed in Beads with commit references.
- [x] `HealthPlugin` works end-to-end (liveness 200; readiness 200/503) via `create_test_client`.
- [x] Full gate green, coverage ≥ 80%.
- [x] `tech-stack.md` reflects litestar as a runtime dependency.

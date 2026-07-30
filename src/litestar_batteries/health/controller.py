"""Health-check controller factory."""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from litestar import Controller, get
from litestar.openapi.datastructures import ResponseSpec
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from litestar_batteries.health.models import CheckResult, HealthReport

if TYPE_CHECKING:
    from litestar_batteries.health.models import HealthCheck, HealthConfig


class _DeadlineExceeded(Exception):
    """Internal marker: the readiness wrapper's per-check timeout elapsed."""


async def _run_check(hc: HealthCheck) -> None:
    """Await ``hc.check()``, bounded by ``hc.timeout`` when set.

    Raises ``_DeadlineExceeded`` only when the wrapper's own deadline elapses. An
    exception raised by the check itself — including an ``asyncio.TimeoutError`` from
    its own client — propagates unchanged so it keeps its real message. The two are
    told apart by *mechanism* (a task still pending past the deadline), because
    ``asyncio.wait_for`` conflates them by exception type.
    """
    if hc.timeout is None:
        await hc.check()
        return
    task = asyncio.ensure_future(hc.check())
    done, _pending = await asyncio.wait({task}, timeout=hc.timeout)
    if task not in done:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        raise _DeadlineExceeded
    task.result()  # re-raise the check's own exception, if it failed


def build_health_controller(config: HealthConfig) -> type[Controller]:
    """Build a ``Controller`` subclass configured from ``config``."""
    checks = tuple(config.checks)

    class HealthController(Controller):
        path = config.path

        @get()
        async def liveness(self) -> HealthReport:
            return HealthReport(status="ok")

        @get(
            "/ready",
            responses={
                HTTP_503_SERVICE_UNAVAILABLE: ResponseSpec(
                    data_container=HealthReport,
                    description="One or more readiness checks failed.",
                ),
            },
        )
        async def readiness(self) -> Response[HealthReport]:
            # Checks run sequentially in registration order; a slow check delays the
            # rest (bounded by its own ``timeout`` when set). Keep individual checks
            # fast, or aggregate concurrently upstream.
            results: list[CheckResult] = []
            healthy = True
            for hc in checks:
                try:
                    await _run_check(hc)
                except _DeadlineExceeded:  # the wrapper's own per-check deadline
                    healthy = False
                    timed_out = f"timed out after {hc.timeout}s"
                    results.append(CheckResult(name=hc.name, status="error", error=timed_out))
                except Exception as exc:  # readiness failure surfaced as a check error
                    healthy = False
                    results.append(CheckResult(name=hc.name, status="error", error=str(exc)))
                else:
                    results.append(CheckResult(name=hc.name, status="ok"))
            report = HealthReport(status="ok" if healthy else "error", checks=results)
            status_code = HTTP_200_OK if healthy else HTTP_503_SERVICE_UNAVAILABLE
            return Response(report, status_code=status_code)

    return HealthController

"""Health-check controller factory."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from litestar import Controller, get
from litestar.openapi.datastructures import ResponseSpec
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from litestar_batteries.health.models import CheckResult, HealthReport

if TYPE_CHECKING:
    from litestar_batteries.health.models import HealthCheck, HealthConfig


class _DeadlineExceeded(Exception):
    """Internal marker: the readiness wrapper's own per-check timeout elapsed."""


class _CheckFailed(Exception):
    """Internal marker: the check raised its own exception; message is preserved."""


async def _guarded(hc: HealthCheck) -> None:
    """Await ``hc.check()``, re-typing a ``TimeoutError`` the check raises itself.

    ``asyncio.wait_for`` raises ``asyncio.TimeoutError`` for *its* deadline, so a
    check that raises ``asyncio.TimeoutError`` on its own (e.g. an upstream client
    timeout) would be indistinguishable from the deadline. Re-raise the check's own
    timeout as ``_CheckFailed`` — preserving its message — so an
    ``asyncio.TimeoutError`` escaping ``wait_for`` uniquely means the deadline.
    """
    try:
        await hc.check()
    except asyncio.TimeoutError as exc:
        raise _CheckFailed(str(exc)) from exc


async def _run_check(hc: HealthCheck) -> None:
    """Await ``hc.check()``, bounded by ``hc.timeout`` when set.

    Raises ``_DeadlineExceeded`` only when the wrapper's own deadline elapses;
    ``asyncio.wait_for`` cancels the check in that case (and propagates cancellation
    when the surrounding request is cancelled, so the check is never orphaned). Any
    failure raised by the check propagates unchanged, keeping its real message.
    """
    if hc.timeout is None:
        await hc.check()
        return
    try:
        await asyncio.wait_for(_guarded(hc), hc.timeout)
    except asyncio.TimeoutError:
        raise _DeadlineExceeded from None


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

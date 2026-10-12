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

__all__ = ["build_health_controller"]


class _DeadlineExceededError(Exception):
    """Internal marker: the readiness wrapper's own per-check timeout elapsed."""


class _CheckFailedError(Exception):
    """Internal marker: the check raised its own exception; message is preserved."""


async def _guarded(hc: HealthCheck) -> None:
    """Await ``hc.check()``, re-typing a ``TimeoutError`` the check raises itself.

    ``asyncio.wait_for`` raises ``asyncio.TimeoutError`` for *its* deadline, so a
    check that raises ``asyncio.TimeoutError`` on its own (e.g. an upstream client
    timeout) would be indistinguishable from the deadline. Re-raise the check's own
    timeout as ``_CheckFailedError`` — preserving its message — so an
    ``asyncio.TimeoutError`` escaping ``wait_for`` uniquely means the deadline.

    Raises:
        _CheckFailedError: The check raised ``TimeoutError`` itself.
    """
    try:
        await hc.check()
    except asyncio.TimeoutError as exc:
        raise _CheckFailedError(str(exc)) from exc


async def _run_check(hc: HealthCheck) -> None:
    """Await ``hc.check()``, bounded by ``hc.timeout`` when set.

    ``asyncio.wait_for`` cancels the check when the deadline elapses (and
    propagates cancellation when the surrounding request is cancelled, so the
    check is never orphaned). Any failure raised by the check propagates
    unchanged, keeping its real message.

    Raises:
        _DeadlineExceededError: The wrapper's own deadline elapsed.
    """
    if hc.timeout is None:
        await hc.check()
        return
    try:
        await asyncio.wait_for(_guarded(hc), hc.timeout)
    except asyncio.TimeoutError:
        raise _DeadlineExceededError from None


async def _evaluate_check(hc: HealthCheck) -> CheckResult:
    """Run one readiness check, translating any failure into an error result.

    A check signals failure by raising (any exception type); a probable
    contract of the battery is that no check exception ever escapes as a 500.

    Returns:
        The check outcome: ``ok``, or ``error`` carrying the failure message.
    """
    try:
        await _run_check(hc)
    except _DeadlineExceededError:
        timed_out = f"timed out after {hc.timeout}s"
        return CheckResult(name=hc.name, status="error", error=timed_out)
    # Any check failure — regardless of exception type — is a readiness error.
    # pylint: disable-next=broad-exception-caught
    except Exception as exc:  # noqa: BLE001
        return CheckResult(name=hc.name, status="error", error=str(exc))
    return CheckResult(name=hc.name, status="ok")


def build_health_controller(config: HealthConfig) -> type[Controller]:
    """Build a ``Controller`` subclass configured from ``config``.

    Returns:
        A controller serving liveness at ``config.path`` and readiness below it.
    """
    checks = tuple(config.checks)

    class HealthController(Controller):
        path: str = config.path

        @get()
        # Litestar route handlers must be instance methods.
        async def liveness(self) -> HealthReport:  # noqa: PLR6301
            """Report liveness unconditionally (the process is up).

            Returns:
                An ``ok`` report with no check details.
            """
            return HealthReport(status="ok")

        @get(
            "/ready",
            responses={
                HTTP_503_SERVICE_UNAVAILABLE: ResponseSpec(
                    data_container=HealthReport,
                    description="One or more readiness checks failed.",
                )
            },
        )
        # Litestar route handlers must be instance methods.
        async def readiness(self) -> Response[HealthReport]:  # noqa: PLR6301
            """Run every check sequentially and report readiness as 200/503.

            Returns:
                ``200`` with per-check results when every check passes, else
                ``503`` carrying each failure message.
            """
            # Checks run sequentially in registration order; a slow check delays
            # the rest (bounded by its own ``timeout`` when set). Keep individual
            # checks fast, or aggregate concurrently upstream.
            results = [await _evaluate_check(hc) for hc in checks]
            healthy = all(result.status == "ok" for result in results)
            report = HealthReport(status="ok" if healthy else "error", checks=results)
            status_code = HTTP_200_OK if healthy else HTTP_503_SERVICE_UNAVAILABLE
            return Response(report, status_code=status_code)

    return HealthController

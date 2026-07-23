"""Health-check controller factory."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar import Controller, get
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from litestar_batteries.health.models import CheckResult, HealthReport

if TYPE_CHECKING:
    from litestar_batteries.health.models import HealthConfig


def build_health_controller(config: HealthConfig) -> type[Controller]:
    """Build a ``Controller`` subclass configured from ``config``."""
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
                except Exception as exc:  # readiness failure surfaced as a check error
                    healthy = False
                    results.append(CheckResult(name=hc.name, status="error", error=str(exc)))
                else:
                    results.append(CheckResult(name=hc.name, status="ok"))
            report = HealthReport(status="ok" if healthy else "error", checks=results)
            status_code = HTTP_200_OK if healthy else HTTP_503_SERVICE_UNAVAILABLE
            return Response(report, status_code=status_code)

    return HealthController

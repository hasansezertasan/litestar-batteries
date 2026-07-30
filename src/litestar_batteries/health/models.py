"""Data types for the health-check battery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

import msgspec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

Status = Literal["ok", "error"]
"""Health status of a check or the overall report."""


class CheckResult(msgspec.Struct):
    """Outcome of a single readiness check."""

    name: str
    status: Status
    error: str | None = None


class HealthReport(msgspec.Struct):
    """Aggregate health/readiness report."""

    status: Status
    # msgspec treats an empty-literal default as a per-instance factory (no shared state).
    checks: list[CheckResult] = []


@dataclass(frozen=True)
class HealthCheck:
    """A named async readiness check that raises on failure.

    ``timeout`` bounds a single run of ``check`` (in seconds). When it is ``None``
    (the default) the check awaits without a time limit; when set, exceeding it
    surfaces as a check error (readiness responds ``503``).
    """

    name: str
    check: Callable[[], Awaitable[None]]
    timeout: float | None = None


@dataclass
class HealthConfig:
    """Configuration for the health plugin."""

    path: str = "/health"
    checks: Sequence[HealthCheck] = field(default_factory=tuple)

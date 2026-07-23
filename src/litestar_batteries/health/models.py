"""Data types for the health-check battery."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import msgspec

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence


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

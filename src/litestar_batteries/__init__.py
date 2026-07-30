"""litestar-batteries: batteries-included utilities for Litestar."""

from importlib.metadata import PackageNotFoundError, version

from litestar_batteries.health import (
    CheckResult,
    HealthCheck,
    HealthConfig,
    HealthPlugin,
    HealthReport,
)
from litestar_batteries.idempotency import IdempotencyConfig, IdempotencyPlugin

try:
    __version__ = version("litestar-batteries")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__ = [
    "CheckResult",
    "HealthCheck",
    "HealthConfig",
    "HealthPlugin",
    "HealthReport",
    "IdempotencyConfig",
    "IdempotencyPlugin",
    "__version__",
]

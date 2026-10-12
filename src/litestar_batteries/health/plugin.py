"""Litestar plugin for the health-check battery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.plugins import InitPlugin
from typing_extensions import override

from litestar_batteries.health.controller import build_health_controller
from litestar_batteries.health.models import HealthConfig

if TYPE_CHECKING:
    from litestar.config.app import AppConfig

__all__ = ["HealthPlugin"]


class HealthPlugin(InitPlugin):
    """Registers liveness and readiness endpoints on the application."""

    def __init__(self, config: HealthConfig | None = None) -> None:
        """Store the health configuration, defaulting to a check-free setup.

        Args:
            config: The health configuration to serve. When ``None`` a default
                ``HealthConfig`` (no readiness checks) is used.
        """
        super().__init__()
        self.config: HealthConfig = config or HealthConfig()

    @override
    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        """Register the health controller on the application.

        Args:
            app_config: The application configuration to extend.

        Returns:
            The same configuration with the health route handler appended.
        """
        app_config.route_handlers.append(build_health_controller(self.config))
        return app_config

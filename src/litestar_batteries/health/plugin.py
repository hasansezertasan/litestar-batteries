"""Litestar plugin for the health-check battery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.plugins import InitPlugin

from litestar_batteries.health.controller import build_health_controller
from litestar_batteries.health.models import HealthConfig

if TYPE_CHECKING:
    from litestar.config.app import AppConfig


class HealthPlugin(InitPlugin):
    """Registers liveness and readiness endpoints on the application."""

    def __init__(self, config: HealthConfig | None = None) -> None:
        self.config = config or HealthConfig()

    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        app_config.route_handlers.append(build_health_controller(self.config))
        return app_config

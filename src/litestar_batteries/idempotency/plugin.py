"""Litestar plugin for the idempotency battery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.plugins import InitPlugin

from litestar_batteries.idempotency.middleware import IdempotencyMiddleware
from litestar_batteries.idempotency.models import IdempotencyConfig

if TYPE_CHECKING:
    from litestar.config.app import AppConfig


class IdempotencyPlugin(InitPlugin):
    """Registers the idempotency middleware on the application."""

    def __init__(self, config: IdempotencyConfig | None = None) -> None:
        self.config = config or IdempotencyConfig()

    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        app_config.middleware.append(IdempotencyMiddleware(self.config))
        return app_config

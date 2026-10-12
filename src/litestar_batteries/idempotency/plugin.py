"""Litestar plugin for the idempotency battery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.plugins import InitPlugin
from typing_extensions import override

from litestar_batteries.idempotency.middleware import IdempotencyMiddleware
from litestar_batteries.idempotency.models import IdempotencyConfig

if TYPE_CHECKING:
    from litestar.config.app import AppConfig

__all__ = ["IdempotencyPlugin"]


class IdempotencyPlugin(InitPlugin):
    """Registers the idempotency middleware on the application."""

    def __init__(self, config: IdempotencyConfig | None = None) -> None:
        """Store the idempotency configuration, defaulting to POST + PATCH.

        Args:
            config: The idempotency configuration to enforce. When ``None`` a
                default ``IdempotencyConfig`` is used.
        """
        super().__init__()
        self.config: IdempotencyConfig = config or IdempotencyConfig()

    @override
    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        """Register the idempotency middleware on the application.

        Args:
            app_config: The application configuration to extend.

        Returns:
            The same configuration with the idempotency middleware appended.
        """
        app_config.middleware.append(IdempotencyMiddleware(self.config))
        return app_config

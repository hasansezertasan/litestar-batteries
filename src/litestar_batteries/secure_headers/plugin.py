"""Litestar plugin for the secure-headers battery."""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.plugins import InitPlugin
from typing_extensions import override

from litestar_batteries.secure_headers.hooks import build_before_send
from litestar_batteries.secure_headers.models import SecureHeadersConfig

if TYPE_CHECKING:
    from litestar.config.app import AppConfig

__all__ = ["SecureHeadersPlugin"]


class SecureHeadersPlugin(InitPlugin):
    """Registers a ``before_send`` hook that adds security headers to responses."""

    def __init__(self, config: SecureHeadersConfig | None = None) -> None:
        """Store the secure-headers configuration, defaulting to the safe baseline.

        Args:
            config: The headers to send. When ``None`` a default
                ``SecureHeadersConfig`` is used.
        """
        super().__init__()
        self.config: SecureHeadersConfig = config or SecureHeadersConfig()

    @override
    def on_app_init(self, app_config: AppConfig) -> AppConfig:
        """Append the secure-headers hook, preserving any user ``before_send`` hooks.

        Args:
            app_config: The application configuration to extend.

        Returns:
            The same configuration with the hook appended.
        """
        app_config.before_send.append(build_before_send(self.config))
        return app_config

"""``before_send`` hook that stamps security headers on HTTP responses.

A ``before_send`` hook (rather than route middleware) is used because it also
covers router-level 404/405 responses that route middleware never sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.datastructures import MutableScopeHeaders

if TYPE_CHECKING:
    from collections.abc import Callable

    from litestar.types import Message, Scope

    from litestar_batteries.secure_headers.models import SecureHeadersConfig

__all__ = ["build_before_send"]


def _apply(
    headers: MutableScopeHeaders, items: tuple[tuple[str, str], ...], *, override: bool
) -> None:
    """Write ``items`` into ``headers``; handler-set values win unless overriding."""
    for name, value in items:
        if override:
            headers[name] = value
        else:
            headers.setdefault(name, value)  # pyright: ignore[reportUnknownMemberType]


def build_before_send(config: SecureHeadersConfig) -> Callable[[Message, Scope], None]:
    """Build the ``before_send`` hook for ``config``.

    Headers are computed once here rather than per response.

    Args:
        config: The secure-headers configuration.

    Returns:
        A hook adding the configured headers to ``http.response.start``.
    """
    static = config.response_headers()
    hsts = config.hsts_value()
    hsts_items = (("strict-transport-security", hsts),) if hsts else ()
    override = config.override

    def secure_headers_hook(message: Message, scope: Scope) -> None:
        if message["type"] != "http.response.start":
            return
        headers = MutableScopeHeaders.from_message(message)
        _apply(headers, static, override=override)
        # ASGI makes ``scheme`` optional (default ``http``).
        if scope.get("scheme") == "https":  # pyright: ignore[reportUnknownMemberType]
            _apply(headers, hsts_items, override=override)

    return secure_headers_hook

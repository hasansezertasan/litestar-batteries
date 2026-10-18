"""``before_send`` hook that stamps security headers on HTTP responses.

A ``before_send`` hook (rather than route middleware) is used because it also
covers router-level 404/405 responses that route middleware never sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from litestar.datastructures import MutableScopeHeaders

from litestar_batteries.secure_headers.models import hsts_value, response_headers

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from litestar.types import Message, Scope

    from litestar_batteries.secure_headers.models import SecureHeadersConfig

__all__ = ["build_before_send"]


def _apply(
    headers: MutableScopeHeaders, items: tuple[tuple[str, str], ...], *, override: bool
) -> None:
    """Write ``items`` into ``headers``; handler-set values win unless overriding."""
    for name, value in items:
        if override:
            # ``del`` removes every copy (``__setitem__`` leaves stale duplicates
            # when a handler set three or more).
            del headers[name]
            headers.add(name, value)
        else:
            headers.setdefault(name, value)  # pyright: ignore[reportUnknownMemberType]


def build_before_send(
    config: SecureHeadersConfig,
) -> Callable[[Message, Scope], Awaitable[None]]:
    """Build the ``before_send`` hook for ``config``.

    Headers are computed once here rather than per response.

    Args:
        config: The secure-headers configuration.

    Returns:
        An async hook adding the configured headers to ``http.response.start``.
    """
    static = response_headers(config)
    hsts = hsts_value(config)
    hsts_items = (("strict-transport-security", hsts),) if hsts else ()
    override = config.override

    # Async on purpose: Litestar runs a sync ``before_send`` hook in a worker
    # thread for every ASGI message, body chunks included.
    async def secure_headers_hook(  # noqa: RUF029
        message: Message, scope: Scope
    ) -> None:
        if message["type"] != "http.response.start":
            return
        # ASGI makes ``headers`` optional but Litestar's types require it, and
        # ``from_message`` raises without the key.
        raw = cast("dict[str, object]", cast("object", message))
        _ = raw.setdefault("headers", [])
        headers = MutableScopeHeaders.from_message(message)
        _apply(headers, static, override=override)
        # ASGI makes ``scheme`` optional (default ``http``).
        if scope.get("scheme") == "https":  # pyright: ignore[reportUnknownMemberType]
            _apply(headers, hsts_items, override=override)

    return secure_headers_hook

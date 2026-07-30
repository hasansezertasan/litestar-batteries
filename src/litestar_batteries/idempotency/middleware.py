"""Idempotency ASGI middleware.

Scaffold: passes requests through unchanged. Dedupe behaviour is implemented in a
later task (see ``.agents/specs/idempotency-battery/spec.md``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from litestar.enums import ScopeType
from litestar.middleware import ASGIMiddleware

if TYPE_CHECKING:
    from litestar.types import ASGIApp, Receive, Scope, Send

    from litestar_batteries.idempotency.models import IdempotencyConfig


class IdempotencyMiddleware(ASGIMiddleware):
    """Deduplicate retried unsafe requests carrying an idempotency key."""

    scopes = (ScopeType.HTTP,)

    def __init__(self, config: IdempotencyConfig) -> None:
        self.config = config

    async def handle(self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp) -> None:
        await next_app(scope, receive, send)

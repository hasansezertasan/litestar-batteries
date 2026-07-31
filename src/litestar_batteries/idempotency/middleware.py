"""Idempotency ASGI middleware.

Deduplicates retried unsafe requests carrying an ``Idempotency-Key`` header by
replaying the first response. See ``.agents/specs/idempotency-battery/spec.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, cast

import msgspec
from litestar import Request
from litestar.enums import ScopeType
from litestar.middleware import ASGIMiddleware
from litestar.status_codes import HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY

from litestar_batteries.idempotency.models import StoredResponse

if TYPE_CHECKING:
    from typing import Any

    from litestar.types import ASGIApp, Message, Receive, ReceiveMessage, Scope, Send

    from litestar_batteries.idempotency.models import IdempotencyConfig


def store_key(method: str, path: str, key: str) -> str:
    """Namespace the idempotency key by method and path so the same key on
    different endpoints cannot collide.

    The path is length-delimited so that a ``:`` inside a path or key cannot make
    two distinct ``(path, key)`` pairs map to the same string.
    """
    return f"{method}:{len(path)}:{path}:{key}"


async def _buffer_request(receive: Receive) -> tuple[bytes, Receive, bool]:
    """Drain the request body from ``receive``; return it, a replay receive, and
    whether the client disconnected before the body was fully received.

    ASGI bodies can only be consumed once, so the middleware buffers the messages
    to fingerprint the body, then hands the downstream app a ``receive`` that
    replays them verbatim.
    """
    messages: list[ReceiveMessage] = []
    body = bytearray()
    disconnected = False
    while True:
        message = await receive()
        messages.append(message)
        if message["type"] == "http.request":
            body.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        else:  # http.disconnect
            disconnected = True
            break

    iterator = iter(messages)

    async def replay() -> ReceiveMessage:
        try:
            return next(iterator)
        except StopIteration:  # pragma: no cover - defensive; body is fully buffered above
            return cast("ReceiveMessage", {"type": "http.request", "body": b"", "more_body": False})

    return bytes(body), replay, disconnected


async def _send_error(send: Send, status: int, detail: str) -> None:
    body = msgspec.json.encode({"detail": detail})
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body, "more_body": False})


async def _replay(send: Send, record: StoredResponse) -> None:
    headers: list[tuple[bytes, bytes]] = [
        (b"idempotency-replayed", b"true"),
        (b"content-length", str(len(record.body)).encode()),
    ]
    if record.media_type is not None:
        headers.append((b"content-type", record.media_type.encode()))
    await send({"type": "http.response.start", "status": record.status, "headers": headers})
    await send({"type": "http.response.body", "body": record.body, "more_body": False})


class IdempotencyMiddleware(ASGIMiddleware):
    """Deduplicate retried unsafe requests carrying an idempotency key.

    On a configured method carrying the idempotency header: a repeated key replays
    the first response (``422`` if the same key arrives with a different body,
    ``409`` while the first request is still in flight). Responses with a ``5xx``
    status are not cached, so a failed request can be retried. Requests without the
    header, or on non-configured methods, pass through untouched.
    """

    scopes = (ScopeType.HTTP,)

    def __init__(self, config: IdempotencyConfig) -> None:
        self.config = config
        self._methods = frozenset(method.upper() for method in config.methods)
        # Serializes the get -> set-sentinel window so two concurrent first requests
        # in the same worker cannot both start. Cross-process dedupe still relies on
        # the store; the Store ABC has no atomic check-and-set, so in-flight
        # detection across workers is best-effort, not a distributed lock.
        self._lock = asyncio.Lock()

    async def handle(self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp) -> None:
        request: Request[Any, Any, Any] = Request(scope)
        if request.method not in self._methods:
            await next_app(scope, receive, send)
            return
        key = request.headers.get(self.config.header_name)
        if not key:
            await next_app(scope, receive, send)
            return

        body, buffered_receive, disconnected = await _buffer_request(receive)
        if disconnected:
            # Client went away before we had a full request; don't persist anything.
            await next_app(scope, buffered_receive, send)
            return
        request_hash = hashlib.sha256(body).hexdigest()
        store = request.app.stores.get(self.config.store)
        record_key = store_key(request.method, request.url.path, key)

        async with self._lock:
            existing_raw = await store.get(record_key)
            record = (
                None
                if existing_raw is None
                else msgspec.msgpack.decode(existing_raw, type=StoredResponse)
            )
            if record is None:
                sentinel = StoredResponse(state="processing", request_hash=request_hash)
                await store.set(
                    record_key, msgspec.msgpack.encode(sentinel), expires_in=self.config.lock_ttl
                )

        if record is not None:
            if record.state == "processing":
                await _send_error(
                    send, HTTP_409_CONFLICT, "A request with this Idempotency-Key is in progress."
                )
            elif record.request_hash != request_hash:
                await _send_error(
                    send,
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    "Idempotency-Key reused with a different request body.",
                )
            else:
                await _replay(send, record)
            return

        status = 0
        media_type: str | None = None
        captured_body = bytearray()

        async def send_wrapper(message: Message) -> None:
            nonlocal status, media_type
            if message["type"] == "http.response.start":
                status = message["status"]
                for name, value in message["headers"]:
                    if name.lower() == b"content-type":
                        media_type = value.decode("latin-1")
                        break
            elif message["type"] == "http.response.body":
                captured_body.extend(message["body"])
            await send(message)

        try:
            await next_app(scope, buffered_receive, send_wrapper)
        except Exception:  # pragma: no cover - Litestar renders handler errors to a 5xx response;
            await store.delete(record_key)  # this guards only ASGI-level failures below the app
            raise

        # Cache only final, faithfully-replayable responses: 2xx and 4xx. A 3xx
        # redirect is skipped because _replay does not carry its Location header;
        # 5xx (and a status of 0 from a handler that never responded) must be
        # retryable. Oversized bodies are served but not stored, to bound memory.
        cacheable = 200 <= status < 300 or 400 <= status < 500
        max_bytes = self.config.max_body_bytes
        too_large = max_bytes is not None and len(captured_body) > max_bytes
        if cacheable and not too_large:
            done = StoredResponse(
                state="done",
                request_hash=request_hash,
                status=status,
                media_type=media_type,
                body=bytes(captured_body),
            )
            await store.set(record_key, msgspec.msgpack.encode(done), expires_in=self.config.ttl)
        else:
            await store.delete(record_key)  # not cached → let a retry re-run

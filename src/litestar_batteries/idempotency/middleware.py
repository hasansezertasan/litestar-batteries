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
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from litestar_batteries.idempotency.models import StoredResponse

if TYPE_CHECKING:
    from typing import Any

    from litestar.stores.base import Store
    from litestar.types import ASGIApp, Message, Receive, ReceiveMessage, Scope, Send

    from litestar_batteries.idempotency.models import IdempotencyConfig

_PROBLEM_BASE = "urn:litestar-batteries:idempotency"


def store_key(method: str, path: str, key: str, scope: str = "") -> str:
    """Namespace the idempotency key by scope, method, and path.

    Every component is length-delimited so a ``:`` inside a scope, path, or key
    cannot make two distinct tuples collide onto the same record.
    """
    return f"{method}:{len(scope)}:{scope}:{len(path)}:{path}:{key}"


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


async def _problem(send: Send, status: int, slug: str, title: str, detail: str) -> None:
    """Send an RFC 9457 ``application/problem+json`` error response."""
    body = msgspec.json.encode(
        {"type": f"{_PROBLEM_BASE}:{slug}", "title": title, "status": status, "detail": detail}
    )
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"application/problem+json"),
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
    headers.extend(
        (name.encode("latin-1"), value.encode("latin-1")) for name, value in record.headers
    )
    await send({"type": "http.response.start", "status": record.status, "headers": headers})
    await send({"type": "http.response.body", "body": record.body, "more_body": False})


class IdempotencyMiddleware(ASGIMiddleware):
    """Deduplicate retried unsafe requests carrying an idempotency key.

    On a configured method carrying the idempotency header: a repeated key replays
    the first response (``422`` if the same key arrives with a different body,
    ``409`` while the first request is still in flight). Non-2xx/4xx responses
    (redirects, ``5xx``) are not cached, so a failed request can be retried.
    Requests without the header (unless ``require_key``), or on non-configured
    methods, pass through untouched. Errors are RFC 9457 ``problem+json``.
    """

    scopes = (ScopeType.HTTP,)

    def __init__(self, config: IdempotencyConfig) -> None:
        self.config = config
        self._methods = frozenset(method.upper() for method in config.methods)
        # Serializes the get -> set-sentinel window so two concurrent first requests
        # in the same worker cannot both start. For a real cross-process guard, set
        # config.claim (the Store ABC has no atomic check-and-set); otherwise
        # in-flight detection across workers is best-effort, not a distributed lock.
        self._lock = asyncio.Lock()

    async def handle(self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp) -> None:
        config = self.config
        request: Request[Any, Any, Any] = Request(scope)
        if request.method not in self._methods:
            await next_app(scope, receive, send)
            return

        key = request.headers.get(config.header_name)
        if not key:
            if config.require_key:
                await _problem(
                    send,
                    HTTP_400_BAD_REQUEST,
                    "missing-key",
                    "Missing Idempotency-Key",
                    f"This endpoint requires an {config.header_name} header.",
                )
                return
            await next_app(scope, receive, send)
            return
        if len(key) > config.max_key_length or not (key.isascii() and key.isprintable()):
            await _problem(
                send,
                HTTP_400_BAD_REQUEST,
                "invalid-key",
                "Invalid Idempotency-Key",
                f"The {config.header_name} must be printable ASCII of at most "
                f"{config.max_key_length} characters.",
            )
            return

        body, buffered_receive, disconnected = await _buffer_request(receive)
        if disconnected:
            # Client went away before we had a full request; don't persist anything.
            await next_app(scope, buffered_receive, send)
            return
        request_hash = hashlib.sha256(body).hexdigest()
        scope_value = config.scope(request) if config.scope is not None else ""
        record_key = store_key(request.method, request.url.path, key, scope_value)

        claim = config.claim
        store: Store | None = None if claim is not None else request.app.stores.get(config.store)
        sentinel = msgspec.msgpack.encode(
            StoredResponse(state="processing", request_hash=request_hash)
        )

        if claim is not None:
            existing_raw = await claim.claim(record_key, sentinel, ttl=config.lock_ttl)
            record = (
                None
                if existing_raw is None
                else msgspec.msgpack.decode(existing_raw, type=StoredResponse)
            )
        else:
            assert store is not None
            async with self._lock:
                existing_raw = await store.get(record_key)
                record = (
                    None
                    if existing_raw is None
                    else msgspec.msgpack.decode(existing_raw, type=StoredResponse)
                )
                if record is None:
                    await store.set(record_key, sentinel, expires_in=config.lock_ttl)

        async def persist(value: bytes) -> None:
            if claim is not None:
                await claim.set(record_key, value, ttl=config.ttl)
            else:
                assert store is not None
                await store.set(record_key, value, expires_in=config.ttl)

        async def drop() -> None:
            if claim is not None:
                await claim.delete(record_key)
            else:
                assert store is not None
                await store.delete(record_key)

        if record is not None:
            if record.state == "processing":
                await _problem(
                    send,
                    HTTP_409_CONFLICT,
                    "in-progress",
                    "Request in progress",
                    "A request with this Idempotency-Key is already in progress.",
                )
            elif record.request_hash != request_hash:
                await _problem(
                    send,
                    HTTP_422_UNPROCESSABLE_ENTITY,
                    "payload-mismatch",
                    "Idempotency-Key reused",
                    "This Idempotency-Key was already used with a different request body.",
                )
            else:
                await _replay(send, record)
            return

        allow = config.replay_headers
        max_bytes = config.max_body_bytes
        status = 0
        captured_headers: list[tuple[str, str]] = []
        captured_body = bytearray()
        too_large = False

        async def send_wrapper(message: Message) -> None:
            nonlocal status, captured_headers, too_large
            if message["type"] == "http.response.start":
                status = message["status"]
                captured_headers = [
                    (name.decode("latin-1").lower(), value.decode("latin-1"))
                    for name, value in message["headers"]
                    if name.decode("latin-1").lower() in allow
                ]
            elif message["type"] == "http.response.body":
                if not too_large:
                    captured_body.extend(message["body"])
                    if max_bytes is not None and len(captured_body) > max_bytes:
                        # Stop buffering (and drop what we have) so a large or
                        # streaming response can't grow memory without bound.
                        too_large = True
                        captured_body.clear()
            await send(message)

        try:
            await next_app(scope, buffered_receive, send_wrapper)
        except Exception:  # pragma: no cover - Litestar renders handler errors to a 5xx response;
            await drop()  # this guards only ASGI-level failures below the app
            raise

        # Cache only final, faithfully-replayable responses: 2xx and 4xx. Redirects
        # (3xx), 5xx, a never-sent response (status 0), and oversized/streaming
        # bodies are not cached, so a retry re-runs.
        cacheable = 200 <= status < 300 or 400 <= status < 500
        if cacheable and not too_large:
            await persist(
                msgspec.msgpack.encode(
                    StoredResponse(
                        state="done",
                        request_hash=request_hash,
                        status=status,
                        headers=captured_headers,
                        body=bytes(captured_body),
                    )
                )
            )
        else:
            await drop()  # not cached → let a retry re-run

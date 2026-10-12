"""Idempotency ASGI middleware.

Deduplicates retried unsafe requests carrying an ``Idempotency-Key`` header by
replaying the first response. See ``.agents/specs/idempotency-battery/spec.md``.
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from uuid import uuid4

import msgspec
from litestar import Request
from litestar.enums import ScopeType
from litestar.middleware import ASGIMiddleware
from litestar.status_codes import (
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_426_UPGRADE_REQUIRED,
)
from typing_extensions import override

from litestar_batteries.idempotency.models import StoredResponse

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from litestar.stores.base import Store
    from litestar.types import (
        ASGIApp,
        HTTPResponseBodyEvent,
        HTTPResponseStartEvent,
        Message,
        Receive,
        ReceiveMessage,
        Scope,
        Send,
    )

    from litestar_batteries.idempotency.claims import AtomicClaim
    from litestar_batteries.idempotency.models import AnyRequest, IdempotencyConfig

__all__ = ["IdempotencyMiddleware", "store_key"]


_PROBLEM_BASE = "urn:litestar-batteries:idempotency"

_FIRST_SUCCESS_STATUS = 200
_FIRST_REDIRECT_STATUS = 300
_FIRST_CLIENT_ERROR_STATUS = 400
_FIRST_SERVER_ERROR_STATUS = 500


async def _suppress_cancel(operation: Awaitable[None]) -> bool:
    """Shield one await from cancellation, swallowing cancels aimed at us.

    Returns:
        Whether a cancellation arrived while shielding.
    """
    try:
        await asyncio.shield(operation)
    except asyncio.CancelledError:
        return True
    return False


async def _shield_finalization(operation: Awaitable[None]) -> None:
    """Finish a record mutation before propagating cancellation.

    Repeated cancels arriving mid-mutation are swallowed until the mutation
    completes; whether any arrived is then re-raised so the caller still
    observes the cancellation.

    Raises:
        asyncio.CancelledError: A cancellation arrived while shielding.
    """
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        cancelled |= await _suppress_cancel(task)
    task.result()
    if cancelled:
        raise asyncio.CancelledError


def store_key(method: str, path: str, key: str, scope: str = "") -> str:
    """Namespace the idempotency key by scope, method, and path.

    Every component is length-delimited so a ``:`` inside a scope, path, or key
    cannot make two distinct tuples collide onto the same record.

    Returns:
        The length-delimited store key for the scoped idempotency record.
    """
    return f"{method}:{len(scope)}:{scope}:{len(path)}:{path}:{key}"


def _replay_receive(messages: list[ReceiveMessage], receive: Receive) -> Receive:
    """Build a receive channel replaying buffered messages, then delegating.

    Returns:
        A ``receive`` callable serving ``messages`` in order before delegating
        to ``receive`` for subsequent calls.
    """
    iterator = iter(messages)

    async def replay() -> ReceiveMessage:
        try:
            return next(iterator)
        except StopIteration:
            return await receive()

    return replay


async def _buffer_request(
    receive: Receive, max_bytes: int | None = None
) -> tuple[bytes, Receive, bool, bool]:
    """Drain the request body from ``receive``.

    ASGI bodies can only be consumed once, so the middleware buffers the messages
    to fingerprint the body, then hands the downstream app a ``receive`` that
    replays them verbatim, then delegates subsequent calls to the original
    ``receive`` so downstream apps can observe client disconnects.

    Returns:
        The body bytes, the replaying ``receive`` channel, whether the client
        disconnected before the body was fully received, and whether the body
        exceeded ``max_bytes`` (reading stops as soon as it does).
    """
    messages: list[ReceiveMessage] = []
    body = bytearray()
    disconnected = False
    too_large = False
    while True:
        message = await receive()
        if message["type"] == "http.request":
            chunk = message.get("body", b"")
            if max_bytes is not None and len(body) + len(chunk) > max_bytes:
                too_large = True
                break
            messages.append(message)
            body.extend(chunk)
            if not message.get("more_body", False):
                break
        else:  # http.disconnect
            messages.append(message)
            disconnected = True
            break

    return bytes(body), _replay_receive(messages, receive), disconnected, too_large


async def _problem(send: Send, status: int, slug: str, title: str, detail: str) -> None:
    """Send an RFC 9457 ``application/problem+json`` error response."""
    body = msgspec.json.encode({
        "type": f"{_PROBLEM_BASE}:{slug}",
        "title": title,
        "status": status,
        "detail": detail,
    })
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/problem+json"),
            (b"content-length", str(len(body)).encode()),
        ],
    })
    await send({"type": "http.response.body", "body": body, "more_body": False})


def _is_cacheable(status: int) -> bool:
    # 426 requires hop-by-hop Upgrade metadata, which replay intentionally omits.
    return (
        _FIRST_SUCCESS_STATUS <= status < _FIRST_REDIRECT_STATUS
        or _FIRST_CLIENT_ERROR_STATUS <= status < _FIRST_SERVER_ERROR_STATUS
    ) and status != HTTP_426_UPGRADE_REQUIRED


def _encode_done(
    request_hash: str, status: int, headers: list[tuple[str, str]], body: bytearray
) -> bytes:
    return msgspec.msgpack.encode(
        StoredResponse(
            state="done",
            request_hash=request_hash,
            status=status,
            headers=headers,
            body=bytes(body),
        )
    )


async def _too_large(send: Send, limit: int) -> None:
    await _problem(
        send,
        HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        "request-too-large",
        "Request body too large",
        f"Requests carrying an idempotency key are limited to {limit} bytes.",
    )


async def _replay(send: Send, record: StoredResponse) -> None:
    headers: list[tuple[bytes, bytes]] = [(b"idempotency-replayed", b"true")]
    if record.status != HTTP_204_NO_CONTENT:  # RFC 9110 §8.6: no Content-Length on 204
        headers.append((b"content-length", str(len(record.body)).encode()))
    headers.extend(
        (name.encode("latin-1"), value.encode("latin-1"))
        for name, value in record.headers
    )
    await send({
        "type": "http.response.start",
        "status": record.status,
        "headers": headers,
    })
    await send({"type": "http.response.body", "body": record.body, "more_body": False})


def _fingerprint(scope: Scope, request: AnyRequest, body: bytes) -> str:
    """Hash the query string, body-representation headers, and raw body.

    Length-frame each component: headers determine how the raw body is
    interpreted.

    Returns:
        Hex digest namespacing the key to one request representation.
    """
    digest = hashlib.sha256()
    for component in (
        scope["query_string"],
        request.headers.get("content-type", "").encode("latin-1"),
        request.headers.get("content-encoding", "").encode("latin-1"),
        body,
    ):
        digest.update(len(component).to_bytes(8, "big"))
        digest.update(component)
    return digest.hexdigest()


def _scope_value(config: IdempotencyConfig, request: AnyRequest) -> str:
    """Resolve the tenant scope folded into the store key.

    Returns:
        The configured scope string, or "" for the global scope.
    """
    return config.scope(request) if config.scope is not None else ""


async def _serve_existing(
    send: Send, record: StoredResponse, request_hash: str
) -> None:
    """Answer a repeat key from the stored record: replay, 422, or 409."""
    if record.state == "processing":
        await _problem(
            send,
            HTTP_409_CONFLICT,
            "in-progress",
            "Request in progress",
            "A request with this Idempotency-Key is already in progress.",
        )
        return
    if record.request_hash != request_hash:
        await _problem(
            send,
            HTTP_422_UNPROCESSABLE_ENTITY,
            "payload-mismatch",
            "Idempotency-Key reused",
            "This Idempotency-Key was already used with a different request body.",
        )
        return
    await _replay(send, record)


@dataclass
class _RecordWriter:
    """Persist or release the record guarded by reservation ownership."""

    claim: AtomicClaim | None
    store: Store | None
    lock: asyncio.Lock
    record_key: str
    sentinel: bytes
    ttl: int

    async def persist(self, value: bytes) -> None:
        """Store a completed response unless the reservation changed hands.

        Raises:
            RuntimeError: The writer carries no store (unreachable invariant).
        """
        if self.claim is not None:
            # The reservation may have lapsed; then there is nothing to persist.
            _ = await self.claim.set(
                self.record_key, value, expected=self.sentinel, ttl=self.ttl
            )
            return
        store = self.store
        if store is None:  # pragma: no cover - unreachable invariant.
            msg = "store-backed record writer has no store"
            raise RuntimeError(msg)
        async with self.lock:
            if await store.get(self.record_key) == self.sentinel:
                await store.set(self.record_key, value, expires_in=self.ttl)

    async def drop(self) -> None:
        """Release the reservation unless it changed hands.

        Raises:
            RuntimeError: The writer carries no store (unreachable invariant).
        """
        if self.claim is not None:
            # The reservation may have lapsed; then there is nothing to release.
            _ = await self.claim.delete(self.record_key, expected=self.sentinel)
            return
        store = self.store
        if store is None:  # pragma: no cover - unreachable invariant.
            msg = "store-backed record writer has no store"
            raise RuntimeError(msg)
        async with self.lock:
            if await store.get(self.record_key) == self.sentinel:
                await store.delete(self.record_key)


# Eight fields mirror the ASGI message kinds being recorded; splitting this
# state bag would obscure the capture pipeline for no behavioral gain.
@dataclass
class _Capture:  # pylint: disable=too-many-instance-attributes
    """Mutable capture state for one downstream response being recorded."""

    allow: frozenset[str]
    max_bytes: int | None
    status: int = 0
    headers: list[tuple[str, str]] = field(default_factory=list)
    body: bytearray = field(default_factory=bytearray)
    too_large: bool = False
    complete: bool = False
    has_trailers: bool = False


def _note_start(capture: _Capture, message: HTTPResponseStartEvent) -> None:
    """Record response-start metadata (status, trailers flag, allow-listed headers)."""
    capture.status = message["status"]
    # `trailers` is an ASGI extension absent from litestar's event types.
    capture.has_trailers = bool(dict(message).get("trailers", False))
    capture.headers = [
        (name.decode("latin-1").lower(), value.decode("latin-1"))
        for name, value in message.get("headers", [])
        if name.decode("latin-1").lower() in capture.allow
    ]


def _note_body(capture: _Capture, message: HTTPResponseBodyEvent) -> None:
    """Record one response-body chunk, short-circuiting past the size cap."""
    capture.complete = not message.get("more_body", False)
    chunk = message.get("body", b"")
    if capture.too_large:
        return
    if (
        capture.max_bytes is not None
        and len(capture.body) + len(chunk) > capture.max_bytes
    ):
        # Stop buffering (and drop what we have) so a large or streaming
        # response can't grow memory without bound.
        capture.too_large = True
        capture.body.clear()
    else:
        capture.body.extend(chunk)


async def _capture_send(capture: _Capture, send: Send, message: Message) -> None:
    """Record start/body metadata, then forward the message downstream."""
    if message["type"] == "http.response.start":
        _note_start(capture, message)
    elif message["type"] == "http.response.body":
        _note_body(capture, message)
    await send(message)


def _should_cache(capture: _Capture) -> bool:
    """Decide whether the captured response is final and faithfully replayable.

    Returns:
        Whether the response is cacheable, complete, bounded, and trailer-free.
    """
    return (
        _is_cacheable(capture.status)
        and capture.complete
        and not capture.too_large
        and not capture.has_trailers
    )


async def _settle_error(
    capture: _Capture, writer: _RecordWriter, request_hash: str, exc: BaseException
) -> None:
    """Persist-or-release after downstream raised mid-response.

    Delivery can fail (e.g. client disconnect -> OSError) after the handler's
    side effect ran. Never release the claim then, or the client's natural retry
    would re-execute it: persist the response if it was fully captured, else
    leave the in-flight marker to expire (409 until lock_ttl).
    """
    if capture.status == 0 and not isinstance(exc, asyncio.CancelledError):
        await _shield_finalization(writer.drop())
    elif _should_cache(capture):
        await _shield_finalization(
            writer.persist(
                _encode_done(
                    request_hash, capture.status, capture.headers, capture.body
                )
            )
        )


async def _settle_success(
    capture: _Capture, writer: _RecordWriter, request_hash: str
) -> None:
    """Persist-or-release after downstream returned normally.

    Cache only final, faithfully-replayable responses: 2xx and 4xx. Redirects
    (3xx), 5xx, a never-sent response (status 0), and oversized/streaming bodies
    are not cached, so a retry re-runs.
    """
    if _should_cache(capture):
        await _shield_finalization(
            writer.persist(
                _encode_done(
                    request_hash, capture.status, capture.headers, capture.body
                )
            )
        )
    else:
        await _shield_finalization(writer.drop())  # not cached → let a retry re-run


@dataclass
class _CaptureSession:
    """Run one first request downstream while recording a replayable response."""

    writer: _RecordWriter
    capture: _Capture
    request_hash: str

    async def run(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        """Forward the request, settling the record on return or on error.

        Raises:
            asyncio.CancelledError: Cancellation arrived (re-raised after settling).
        """
        capture = self.capture

        async def send_wrapper(message: Message) -> None:
            await _capture_send(capture, send, message)

        try:
            await next_app(scope, receive, send_wrapper)
        # Delivery/handler failure must settle the record before propagating.
        except (Exception, asyncio.CancelledError) as exc:
            # pylint: disable-next=broad-exception-caught
            await _settle_error(capture, self.writer, self.request_hash, exc)
            raise
        await _settle_success(capture, self.writer, self.request_hash)


class IdempotencyMiddleware(ASGIMiddleware):
    """Deduplicate retried unsafe requests carrying an idempotency key.

    On a configured method carrying the idempotency header: a repeated key replays
    the first response (``422`` if the same key arrives with a different body,
    ``409`` while the first request is still in flight). Non-2xx/4xx responses
    (redirects, ``5xx``) are not cached, so a failed request can be retried.
    Requests without the header (unless ``require_key``), or on non-configured
    methods, pass through untouched. Errors are RFC 9457 ``problem+json``.
    """

    scopes: tuple[ScopeType, ...] = (ScopeType.HTTP,)

    def __init__(self, config: IdempotencyConfig) -> None:
        """Store config and precompute the upper-cased method set and lock.

        Args:
            config: The idempotency configuration to enforce.
        """
        self.config: IdempotencyConfig = config
        self._methods: frozenset[str] = frozenset(
            method.upper() for method in config.methods
        )
        # Serializes the get -> set-sentinel window so two concurrent first requests
        # in the same worker cannot both start. For a real cross-process guard, set
        # config.claim (the Store ABC has no atomic check-and-set); otherwise
        # in-flight detection across workers is best-effort, not a distributed lock.
        self._lock: asyncio.Lock = asyncio.Lock()

    async def _resolve_key(
        self, request: AnyRequest, receive: Receive, send: Send, next_app: ASGIApp
    ) -> str | None:
        """Resolve a usable idempotency key, passing keyless requests through.

        Non-configured methods and (unless ``require_key``) keyless requests are
        forwarded to ``next_app`` untouched; missing-required and invalid keys
        get a ``400`` problem response.

        Returns:
            The validated key, or ``None`` when the response was already sent.
        """
        config = self.config
        if request.method not in self._methods:
            await next_app(request.scope, receive, send)
            return None
        key = request.headers.get(config.header_name)
        if key is None:
            if config.require_key:
                await _problem(
                    send,
                    HTTP_400_BAD_REQUEST,
                    "missing-key",
                    "Missing Idempotency-Key",
                    f"This endpoint requires an {config.header_name} header.",
                )
            else:
                await next_app(request.scope, receive, send)
            return None
        if (
            not key
            or len(key) > config.max_key_length
            or not (key.isascii() and key.isprintable())
        ):
            await _problem(
                send,
                HTTP_400_BAD_REQUEST,
                "invalid-key",
                "Invalid Idempotency-Key",
                "".join([
                    f"The {config.header_name} must be printable ASCII",
                    f" of at most {config.max_key_length} characters.",
                ]),
            )
            return None
        return key

    async def _prepare_body(
        self, request: AnyRequest, receive: Receive, send: Send, next_app: ASGIApp
    ) -> tuple[bytes, Receive] | None:
        """Buffer and validate the request body for fingerprinting.

        Bodies over the byte cap get ``413``; requests whose client went away
        before the body completed pass through unpersisted.

        Returns:
            The body bytes plus a replaying ``receive`` channel, or ``None``
            when the response was already sent.

        Raises:
            RuntimeError: The body overflowed with no cap set (unreachable).
        """
        config = self.config
        max_request = config.max_request_bytes
        declared = request.headers.get("content-length")
        if (
            max_request is not None
            and declared is not None
            and declared.isdigit()
            and int(declared) > max_request
        ):
            await _too_large(send, max_request)
            return None
        body, buffered_receive, disconnected, oversized = await _buffer_request(
            receive, max_request
        )
        if oversized:
            if max_request is None:  # pragma: no cover - unreachable invariant.
                msg = "oversized body without a configured byte cap"
                raise RuntimeError(msg)
            await _too_large(send, max_request)
            return None
        if disconnected:
            # Client went away before we had a full request; don't persist anything.
            await next_app(request.scope, buffered_receive, send)
            return None
        return body, buffered_receive

    async def _acquire(
        self, request: AnyRequest, record_key: str, sentinel: bytes
    ) -> tuple[StoredResponse | None, _RecordWriter]:
        """Claim the key, returning any existing record plus a guarded writer.

        Returns:
            The decoded existing record (``None`` for a first request) and a
            writer that persists/releases only while still owning the reservation.
        """
        config = self.config
        claim = config.claim
        if claim is not None:
            existing_raw = await claim.claim(record_key, sentinel, ttl=config.lock_ttl)
            record = (
                None
                if existing_raw is None
                else msgspec.msgpack.decode(existing_raw, type=StoredResponse)
            )
            writer = _RecordWriter(
                claim, None, self._lock, record_key, sentinel, config.ttl
            )
            return record, writer
        store = request.app.stores.get(config.store)
        async with self._lock:
            existing_raw = await store.get(record_key)
            record = (
                None
                if existing_raw is None
                else msgspec.msgpack.decode(existing_raw, type=StoredResponse)
            )
            if record is None:
                await store.set(record_key, sentinel, expires_in=config.lock_ttl)
        writer = _RecordWriter(
            None, store, self._lock, record_key, sentinel, config.ttl
        )
        return record, writer

    @override
    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        """Enforce idempotency for one request; see the class docstring."""
        request: AnyRequest = Request(scope)
        key = await self._resolve_key(request, receive, send, next_app)
        if key is None:
            return
        prepared = await self._prepare_body(request, receive, send, next_app)
        if prepared is None:
            return
        request_hash = _fingerprint(scope, request, prepared[0])
        record_key = store_key(
            request.method, request.url.path, key, _scope_value(self.config, request)
        )
        sentinel = msgspec.msgpack.encode(
            StoredResponse(
                state="processing", request_hash=request_hash, owner=uuid4().hex
            )
        )
        record, writer = await self._acquire(request, record_key, sentinel)
        if record is not None:
            await _serve_existing(send, record, request_hash)
            return
        session = _CaptureSession(
            writer,
            _Capture(
                allow=self.config.replay_headers, max_bytes=self.config.max_body_bytes
            ),
            request_hash,
        )
        await session.run(scope, prepared[1], send, next_app)

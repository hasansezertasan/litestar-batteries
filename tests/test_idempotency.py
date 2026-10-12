"""Tests for the idempotency battery."""

from __future__ import annotations

import asyncio
import tracemalloc
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import msgspec
import pytest
from litestar import Litestar, Response, get, post
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_409_CONFLICT,
    HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from litestar.stores.memory import MemoryStore
from litestar.testing import AsyncTestClient, create_test_client

from litestar_batteries import (
    AtomicClaim,
    IdempotencyConfig,
    IdempotencyPlugin,
    RedisAtomicClaim,
)
from litestar_batteries.idempotency.middleware import (
    IdempotencyMiddleware,
    _buffer_request,  # pyright: ignore[reportPrivateUsage]
    store_key,
)
from litestar_batteries.idempotency.models import StoredResponse

if TYPE_CHECKING:
    from litestar.handlers.http_handlers import HTTPRouteHandler
    from litestar.types import ASGIApp, Message, Receive, ReceiveMessage, Scope, Send
PROBLEM_JSON = "application/problem+json"


class _DictClaim(AtomicClaim):
    """In-memory AtomicClaim double for exercising the claim code path."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def claim(self, key: str, value: bytes, *, ttl: int) -> bytes | None:
        _ = ttl  # TTL is intentionally unenforced in this in-memory double.
        if key in self._data:
            return self._data[key]
        self._data[key] = value
        return None

    async def set(self, key: str, value: bytes, *, expected: bytes, ttl: int) -> bool:
        _ = ttl  # TTL is intentionally unenforced in this in-memory double.
        if self._data.get(key) != expected:
            return False
        self._data[key] = value
        return True

    async def delete(self, key: str, *, expected: bytes) -> bool:
        if self._data.get(key) != expected:
            return False
        self._data.pop(key, None)
        return True


class _FakeRedis:
    """Minimal redis.asyncio.Redis stand-in for RedisAtomicClaim."""

    def __init__(self) -> None:
        self.store: dict[str, bytes] = {}

    async def set(
        self, name: str, value: bytes, *, nx: bool = False, ex: int | None = None
    ) -> bool | None:
        _ = ex  # Expiry is intentionally unenforced in this stand-in.
        if nx and name in self.store:
            return None
        self.store[name] = value
        return True

    async def get(self, name: str) -> bytes | None:
        return self.store.get(name)

    async def delete(self, *names: str) -> int:
        removed = 0
        for name in names:
            if name in self.store:
                del self.store[name]
                removed += 1
        return removed

    async def eval(self, script: str, numkeys: int, *args: str | bytes | int) -> int:
        _ = script  # Part of the redis API shape; scripts are fixed strings here.
        _ = numkeys  # Always a single key in this stand-in.
        name, expected = str(args[0]), args[1]
        if self.store.get(name) != expected:
            return 0
        if len(args) == 2:
            return await self.delete(name)
        self.store[name] = cast("bytes", args[2])
        return 1


class _SlowClaim(_DictClaim):
    """Claim double blocking inside set until released (cancellation probe)."""

    def __init__(self) -> None:
        super().__init__()
        self.persist_started = asyncio.Event()
        self.release_persist = asyncio.Event()

    async def set(self, key: str, value: bytes, *, expected: bytes, ttl: int) -> bool:
        self.persist_started.set()
        await self.release_persist.wait()
        return await super().set(key, value, expected=expected, ttl=ttl)


@dataclass
class _CancelScenario:
    """Drive for the cancellation-finalizes test (cancel into send and persist)."""

    middleware: IdempotencyMiddleware
    scope: Scope
    receive: Receive
    send: Send
    downstream: ASGIApp
    cancel_at: str
    send_started: asyncio.Event
    claim: _SlowClaim

    async def run(self) -> None:
        """Cancel mid-send and mid-persist, then report the cancellation."""
        request = asyncio.create_task(
            self.middleware.handle(self.scope, self.receive, self.send, self.downstream)
        )
        try:
            await asyncio.wait_for(
                (
                    self.send_started
                    if self.cancel_at == "send"
                    else self.claim.persist_started
                ).wait(),
                1,
            )
            request.cancel()
            await asyncio.wait_for(self.claim.persist_started.wait(), 1)
            await asyncio.sleep(0)
            # Repeated cancellation must not interrupt the finalization write.
            request.cancel()
            await asyncio.sleep(0)
        finally:
            self.claim.release_persist.set()
            with pytest.raises(asyncio.CancelledError):
                await request


class _ExpiringDownstream:
    """Downstream double planting a newer completed record on first entry."""

    def __init__(
        self,
        store: _FakeRedis,
        newer: IdempotencyMiddleware,
        discard: Send,
        old_status: int,
    ) -> None:
        """Capture the shared drive state for the expired-owner test."""
        self._store = store
        self._newer = newer
        self._discard = discard
        self._old_status = old_status
        self.calls = 0

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve one request, superseding the first entry mid-flight."""
        self.calls += 1
        invocation = self.calls
        if invocation == 1:
            self._store.store.clear()  # lease expires before the original finishes
            await self._newer.handle(scope, receive, self._discard, self)
        await send({
            "type": "http.response.start",
            "status": self._old_status if invocation == 1 else 201,
            "headers": [],
        })
        await send({
            "type": "http.response.body",
            "body": str(invocation).encode(),
            "more_body": False,
        })


REPLAYED_HEADER = "Idempotency-Replayed"


async def _canned_body_receive() -> ReceiveMessage:
    """Serve one canned empty-JSON request body on every call.

    Returns:
        A single complete ``http.request`` message.
    """
    await asyncio.sleep(0)
    return {"type": "http.request", "body": b"{}", "more_body": False}


@pytest.fixture
def anyio_backend() -> str:
    """Run the anyio-marked tests on asyncio.

    Returns:
        The anyio backend name for async tests.
    """
    return "asyncio"


def _counting_create() -> tuple[HTTPRouteHandler, dict[str, int]]:
    """Build a POST handler counting invocations and echoing its body.

    Returns:
        The route handler and its mutable invocation counter.
    """
    calls = {"n": 0}

    @post("/create")
    async def create(data: dict[str, Any]) -> dict[str, Any]:
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"n": calls["n"], "echo": data}

    return create, calls


def test_no_key_passes_through() -> None:
    """Run both requests without dedupe when no key is carried."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        r1 = client.post("/create", json={"a": 1})
        r2 = client.post("/create", json={"a": 1})
        assert r1.status_code == r2.status_code == HTTP_201_CREATED
        assert calls["n"] == 2  # ran both times — no dedupe without a key


def test_get_is_not_deduplicated() -> None:
    """Run GET twice even with a key (not a configured method)."""
    calls = {"n": 0}

    @get("/ping")
    async def ping() -> dict[str, int]:
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"n": calls["n"]}

    with create_test_client(
        route_handlers=[ping], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k"}
        client.get("/ping", headers=headers)
        client.get("/ping", headers=headers)
        assert calls["n"] == 2  # GET is not a configured method


def test_repeated_key_replays_first_response() -> None:
    """Replay the stored response with a replay marker on a key retry."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        r1 = client.post("/create", headers=headers, json={"a": 1})
        r2 = client.post("/create", headers=headers, json={"a": 1})
        assert (
            r1.status_code == r2.status_code == HTTP_201_CREATED
        )  # replay preserves status
        assert calls["n"] == 1  # handler ran only once
        assert r1.json() == r2.json()  # identical replayed body
        assert REPLAYED_HEADER not in r1.headers
        assert r2.headers.get(REPLAYED_HEADER) == "true"


def test_same_key_different_body_conflicts() -> None:
    """Reject a key reused with a different body with 422."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/create", headers=headers, json={"a": 1})
        assert first.status_code == HTTP_201_CREATED
        reused = client.post("/create", headers=headers, json={"a": 999})
        assert reused.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert calls["n"] == 1  # the mismatched retry did not run the handler


def test_5xx_is_not_cached_and_retry_reruns() -> None:
    """Re-run (not replay) a retry after a 5xx response."""
    calls = {"n": 0}

    @post("/flaky")
    async def flaky() -> Response[dict[str, Any]]:
        await asyncio.sleep(0)
        calls["n"] += 1
        if calls["n"] == 1:
            return Response(
                {"error": "boom"}, status_code=HTTP_500_INTERNAL_SERVER_ERROR
            )
        return Response({"ok": True}, status_code=HTTP_200_OK)

    with create_test_client(
        route_handlers=[flaky], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/flaky", headers=headers, json={"a": 1})
        assert first.status_code == HTTP_500_INTERNAL_SERVER_ERROR
        second = client.post("/flaky", headers=headers, json={"a": 1})
        assert second.status_code == HTTP_200_OK  # not replayed — re-ran
        assert calls["n"] == 2


def test_redirect_is_not_cached() -> None:
    """Re-run (not replay) a retry after a redirect response."""
    # 3xx is not replayable (Location header isn't carried), so it must not be cached.
    calls = {"n": 0}

    @post("/go", status_code=302)
    async def go() -> Response[None]:
        await asyncio.sleep(0)
        calls["n"] += 1
        return Response(None, status_code=302, headers={"Location": "/there"})

    with create_test_client(
        route_handlers=[go], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/go", headers=headers, json={"a": 1}, follow_redirects=False)
        client.post("/go", headers=headers, json={"a": 1}, follow_redirects=False)
        assert calls["n"] == 2  # re-ran; the redirect was not cached


def test_oversized_response_is_not_cached() -> None:
    """Re-run (not replay) a retry after an over-cap response."""
    calls = {"n": 0}

    @post("/big")
    async def big() -> dict[str, str]:
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"blob": "x" * 5_000}

    config = IdempotencyConfig(max_body_bytes=1_000)  # smaller than the response
    with create_test_client(
        route_handlers=[big], plugins=[IdempotencyPlugin(config)]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/big", headers=headers, json={"a": 1})
        client.post("/big", headers=headers, json={"a": 1})
        assert calls["n"] == 2  # too large to cache → re-ran


def test_426_is_not_cached_without_upgrade_metadata() -> None:
    """Serve (not cache) a 426 whose hop-by-hop headers cannot be replayed."""
    calls = 0

    @post("/upgrade")
    async def upgrade() -> Response[None]:
        await asyncio.sleep(0)
        nonlocal calls
        calls += 1
        return Response(
            None,
            status_code=426,
            headers={"Upgrade": "HTTP/2", "Connection": "Upgrade"},
        )

    with create_test_client(
        route_handlers=[upgrade], plugins=[IdempotencyPlugin()]
    ) as client:
        for _ in range(2):
            response = client.post(
                "/upgrade", headers={"Idempotency-Key": "k"}, json={}
            )
            assert response.status_code == 426
            assert response.headers["Upgrade"] == "HTTP/2"
            assert REPLAYED_HEADER not in response.headers
    assert calls == 2


@pytest.mark.anyio
async def test_oversized_response_chunk_is_not_copied() -> None:
    """Short-circuit response buffering at the cap without a full-size copy."""
    chunk = b"x" * (2 * 1024 * 1024)
    claim = _DictClaim()
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=claim, max_body_bytes=8))

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(_message: Message) -> None:
        await asyncio.sleep(0)

    async def downstream(_scope: Scope, _receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": chunk, "more_body": False})

    tracemalloc.start()
    try:
        await middleware.handle(
            cast("Scope", _raw_scope("/big", "k")), receive, send, downstream
        )
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert (
        peak < len(chunk) // 2
    )  # the upstream chunk exists before tracing; no full-size copy
    assert await claim.claim(store_key("POST", "/big", "k"), b"probe", ttl=10) is None


def test_same_key_isolated_across_endpoints() -> None:
    """Keep one endpoint's key from colliding with another's via framing."""
    # A ":" in the path must not let one endpoint's key collide with another's.
    calls = {"a": 0, "b": 0}

    @post("/orders:v2")
    async def a() -> dict[str, str]:
        await asyncio.sleep(0)
        calls["a"] += 1
        return {"which": "a"}

    @post("/orders")
    async def b() -> dict[str, str]:
        await asyncio.sleep(0)
        calls["b"] += 1
        return {"which": "b"}

    with create_test_client(
        route_handlers=[a, b], plugins=[IdempotencyPlugin()]
    ) as client:
        ra = client.post("/orders:v2", headers={"Idempotency-Key": "x"}, json={})
        rb = client.post("/orders", headers={"Idempotency-Key": "v2:x"}, json={})
        assert ra.json() == {"which": "a"}  # not cross-replayed
        assert rb.json() == {"which": "b"}
        assert calls == {"a": 1, "b": 1}


def test_custom_header_and_methods() -> None:
    """Honor a custom header while ignoring the default one."""
    calls = {"n": 0}

    @post("/put-like")
    async def handler() -> dict[str, int]:
        await asyncio.sleep(0)
        calls["n"] += 1
        return {"n": calls["n"]}

    config = IdempotencyConfig(header_name="X-Idem", methods=("POST",))
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        # default header is ignored now; the custom one is honored
        client.post("/put-like", headers={"Idempotency-Key": "k"}, json={"a": 1})
        client.post("/put-like", headers={"Idempotency-Key": "k"}, json={"a": 1})
        assert calls["n"] == 2  # default header not recognized
        client.post("/put-like", headers={"X-Idem": "k2"}, json={"a": 1})
        client.post("/put-like", headers={"X-Idem": "k2"}, json={"a": 1})
        assert calls["n"] == 3  # custom header deduped the second call


def test_uses_configured_store() -> None:
    """Dedupe against the explicitly configured Litestar store."""
    handler, calls = _counting_create()
    store = MemoryStore()
    with create_test_client(
        route_handlers=[handler],
        plugins=[IdempotencyPlugin()],
        stores={"idempotency": store},
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        client.post("/create", headers=headers, json={"a": 1})
        assert calls["n"] == 1  # dedupe worked against the provided store


@pytest.mark.anyio
async def test_in_flight_key_returns_409() -> None:
    """Report a seeded in-flight reservation as a 409 conflict."""
    # Deterministically exercise the in-flight branch: seed the exact record a
    # concurrent, still-processing first request would leave, then fire a retry.
    handler, calls = _counting_create()
    app = Litestar(route_handlers=[handler], plugins=[IdempotencyPlugin()])
    async with AsyncTestClient(app=app) as client:
        store = app.stores.get("idempotency")
        sentinel = StoredResponse(state="processing", request_hash="")
        await store.set(
            store_key("POST", "/create", "k1"), msgspec.msgpack.encode(sentinel)
        )

        resp = await client.post(
            "/create", headers={"Idempotency-Key": "k1"}, json={"a": 1}
        )
        assert resp.status_code == HTTP_409_CONFLICT
        assert calls["n"] == 0  # the retry did not run the handler


@pytest.mark.anyio
async def test_buffer_request_reassembles_chunked_body() -> None:
    """Reassemble chunked bodies for fingerprinting and replay them verbatim."""
    chunks: list[ReceiveMessage] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ]
    stream = iter(chunks)

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return next(stream)

    body, replay, disconnected, _big = await _buffer_request(receive)
    assert body == b"abcd"  # chunks reassembled for fingerprinting
    assert not disconnected
    assert (
        cast("dict[str, Any]", await replay())["body"] == b"ab"
    )  # replayed verbatim to the app
    assert cast("dict[str, Any]", await replay())["body"] == b"cd"


@pytest.mark.anyio
async def test_buffer_request_flags_disconnect() -> None:
    """Report a client disconnect arriving before any request body."""

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    body, _replay, disconnected, _big = await _buffer_request(receive)
    assert body == b""
    assert disconnected


@pytest.mark.anyio
async def test_buffered_receive_waits_for_server_disconnect_after_body() -> None:
    """Delegate post-body receives to the server to observe disconnects."""
    body_message: ReceiveMessage = {
        "type": "http.request",
        "body": b"body",
        "more_body": False,
    }
    disconnect: ReceiveMessage = {"type": "http.disconnect"}
    server_waiting = asyncio.Event()
    client_disconnected = asyncio.Event()
    receives = 0

    async def receive() -> ReceiveMessage:
        nonlocal receives
        await asyncio.sleep(0)
        receives += 1
        if receives == 1:
            return body_message
        server_waiting.set()
        await client_disconnected.wait()
        return disconnect

    body, replay, disconnected, oversized = await _buffer_request(receive)
    assert body == b"body"
    assert not disconnected
    assert not oversized
    assert await replay() is body_message
    assert receives == 1  # replaying the body does not read ahead from the server

    async def watch_disconnect() -> ReceiveMessage:
        return await replay()

    watcher = asyncio.create_task(watch_disconnect())
    try:
        await asyncio.wait_for(server_waiting.wait(), 1)
        assert (
            not watcher.done()
        )  # post-body receive blocks until the server sends an event
        client_disconnected.set()
        assert await asyncio.wait_for(watcher, 1) is disconnect
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


def test_scope_isolates_same_key_across_callers() -> None:
    """Isolate identical keys from different scoped callers."""
    handler, calls = _counting_create()
    config = IdempotencyConfig(scope=lambda r: r.headers.get("X-User", "anon"))
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        key = {"Idempotency-Key": "k"}
        client.post("/create", headers={**key, "X-User": "alice"}, json={"a": 1})
        client.post("/create", headers={**key, "X-User": "bob"}, json={"a": 1})
        assert calls["n"] == 2  # same key, different scope -> not cross-replayed
        client.post("/create", headers={**key, "X-User": "alice"}, json={"a": 1})
        assert calls["n"] == 2  # alice's repeat -> replayed


def test_require_key_rejects_missing_key() -> None:
    """Reject a keyless request with 400 when require_key is set."""
    handler, calls = _counting_create()
    config = IdempotencyConfig(require_key=True)
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        resp = client.post("/create", json={"a": 1})
        assert resp.status_code == HTTP_400_BAD_REQUEST
        assert resp.headers["content-type"].startswith(PROBLEM_JSON)
        assert resp.json()["type"].endswith("missing-key")
        assert calls["n"] == 0


def test_invalid_key_is_rejected() -> None:
    """Reject an over-long key with 400."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        resp = client.post(
            "/create", headers={"Idempotency-Key": "x" * 300}, json={"a": 1}
        )
        assert resp.status_code == HTTP_400_BAD_REQUEST
        assert resp.json()["type"].endswith("invalid-key")
        assert calls["n"] == 0


@pytest.mark.parametrize("require_key", [False, True])
def test_explicit_empty_key_is_invalid(*, require_key: bool) -> None:
    """Reject an explicitly empty key with 400 either way."""
    handler, calls = _counting_create()
    config = IdempotencyConfig(require_key=require_key)
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        response = client.post("/create", headers={"Idempotency-Key": ""}, json={})
        assert response.status_code == HTTP_400_BAD_REQUEST
        assert response.json()["type"].endswith("invalid-key")
        assert calls["n"] == 0


def test_error_responses_are_problem_json() -> None:
    """Return key-reuse errors as RFC 9457 problem+json."""
    handler, _calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        mismatch = client.post("/create", headers=headers, json={"a": 2})
        assert mismatch.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert mismatch.headers["content-type"].startswith(PROBLEM_JSON)
        body = mismatch.json()
        assert body["type"].endswith("payload-mismatch")
        assert body["status"] == HTTP_422_UNPROCESSABLE_ENTITY


def test_replays_allowlisted_headers_only() -> None:
    """Replay allow-listed headers while dropping sensitive ones."""

    @post("/make")
    async def make() -> Response[dict[str, bool]]:
        await asyncio.sleep(0)
        return Response({"ok": True}, headers={"ETag": '"abc"', "Set-Cookie": "sid=1"})

    with create_test_client(
        route_handlers=[make], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/make", headers=headers, json={"a": 1})
        replay = client.post("/make", headers=headers, json={"a": 1})
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert replay.headers.get("ETag") == '"abc"'  # allow-listed → replayed
        assert "set-cookie" not in replay.headers  # denied → not replayed


def test_dedupe_via_atomic_claim_backend() -> None:
    """Dedupe, replay, and conflict-mismatch through a claim backend."""
    handler, calls = _counting_create()
    config = IdempotencyConfig(claim=_DictClaim())
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        replay = client.post("/create", headers=headers, json={"a": 1})
        assert calls["n"] == 1  # deduped through the claim backend
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        mismatch = client.post("/create", headers=headers, json={"a": 2})
        assert mismatch.status_code == HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.anyio
async def test_redis_atomic_claim() -> None:
    """Exercise the Redis claim/set/delete ownership round-trip."""
    redis = _FakeRedis()
    claim = RedisAtomicClaim(redis, prefix="idem:")
    assert await claim.claim("k", b"first", ttl=10) is None  # won the reservation
    assert (
        await claim.claim("k", b"second", ttl=10) == b"first"
    )  # lost → incumbent bytes
    assert not await claim.set("k", b"wrong", expected=b"other", ttl=10)
    assert not await claim.delete("k", expected=b"other")
    assert await claim.set("k", b"done", expected=b"first", ttl=10)
    assert redis.store["idem:k"] == b"done"
    assert await claim.delete("k", expected=b"done")
    assert "idem:k" not in redis.store
    assert await redis.delete("a", "b", "c") == 0  # variadic delete, nothing stored


def test_same_key_different_query_string_conflicts() -> None:
    """Fold the query string into the request fingerprint."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create?action=create", headers=headers, json={"a": 1})
        other = client.post("/create?action=cancel", headers=headers, json={"a": 1})
        assert other.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert calls["n"] == 1


@pytest.mark.parametrize(
    ("header", "first_value", "second_value"),
    [
        ("Content-Type", "application/json", "text/plain"),
        ("Content-Encoding", "identity", "gzip"),
    ],
)
def test_representation_headers_are_part_of_request_identity(
    header: str, first_value: str, second_value: str
) -> None:
    """Fold body-representation headers into the request fingerprint."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {
            "Idempotency-Key": "k",
            "Content-Type": "application/json",
            header: first_value,
        }
        first = client.post("/create", headers=headers, content=b'{"a":1}')
        assert first.status_code == HTTP_201_CREATED
        replay = client.post("/create", headers=headers, content=b'{"a":1}')
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        headers[header] = second_value
        mismatch = client.post("/create", headers=headers, content=b'{"a":1}')
        assert mismatch.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert mismatch.json()["type"].endswith("payload-mismatch")
        assert calls["n"] == 1


@pytest.mark.parametrize(
    ("status", "header", "value"),
    [
        (206, "Content-Range", "bytes 0-11/24"),
        (401, "WWW-Authenticate", "Basic"),
        (405, "Allow", "POST"),
        (407, "Proxy-Authenticate", "Basic"),
        (429, "Retry-After", "30"),
    ],
)
def test_replays_required_protocol_headers(
    status: int, header: str, value: str
) -> None:
    """Replay protocol headers required to interpret cached error statuses."""

    @post("/limited")
    async def limited() -> Response[dict[str, bool]]:
        await asyncio.sleep(0)
        return Response({"ok": False}, status_code=status, headers={header: value})

    with create_test_client(
        route_handlers=[limited], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/limited", headers=headers, json={"a": 1})
        replay = client.post("/limited", headers=headers, json={"a": 1})
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert replay.status_code == status
        assert replay.headers.get(header) == value


@pytest.mark.anyio
async def test_redis_claim_retries_when_incumbent_vanishes() -> None:
    """Re-acquire (not phantom-win) when the incumbent vanishes mid-claim."""

    class _Vanishing(_FakeRedis):
        """First GET after a lost SET NX finds the incumbent already gone."""

        def __init__(self) -> None:
            super().__init__()
            self.store["idempotency:k"] = b"incumbent"
            self.gets = 0

        async def get(self, name: str) -> bytes | None:
            self.gets += 1
            if self.gets == 1:
                self.store.pop(name, None)  # incumbent released before our GET
                return None
            return await super().get(name)

    redis = _Vanishing()
    claim = RedisAtomicClaim(redis)
    assert (
        await claim.claim("k", b"mine", ttl=10) is None
    )  # re-acquired, not a phantom win
    assert redis.store["idempotency:k"] == b"mine"
    assert await claim.claim("k", b"other", ttl=10) == b"mine"


@pytest.mark.anyio
async def test_dict_claim_rejects_foreign_owner() -> None:
    """Refuse set/delete from a reservation that changed hands."""
    claim = _DictClaim()
    assert await claim.claim("k", b"mine", ttl=10) is None
    assert not await claim.set("k", b"other", expected=b"stale", ttl=10)
    assert not await claim.delete("k", expected=b"stale")
    assert await claim.delete("k", expected=b"mine")


@pytest.mark.anyio
async def test_streaming_oversized_body_rejected_after_buffering() -> None:
    """Reject a streaming body over the cap with 413 once detected."""
    chunks: list[ReceiveMessage] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cdefgh", "more_body": True},
    ]
    stream = iter(chunks)
    middleware = IdempotencyMiddleware(IdempotencyConfig(max_request_bytes=4))
    scope = cast("Scope", _raw_scope("/upload", "k"))
    responses: list[Any] = []
    downstream_calls = 0

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return next(stream)

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal downstream_calls
        await asyncio.sleep(0)
        downstream_calls += 1

    await middleware.handle(scope, receive, send, downstream)
    assert responses[0]["status"] == HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert downstream_calls == 0  # rejected before the app ran


@pytest.mark.anyio
async def test_mid_request_disconnect_passes_through_unpersisted() -> None:
    """Pass through (never persist) a request whose client goes away mid-body."""
    chunks: list[ReceiveMessage] = [
        {"type": "http.request", "body": b"partial", "more_body": True},
        {"type": "http.disconnect"},
    ]
    stream = iter(chunks)
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=_DictClaim()))
    scope = cast("Scope", _raw_scope("/upload", "k"))
    responses: list[Any] = []
    calls = 0

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return next(stream)

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def downstream(_scope: Scope, _receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok", "more_body": False})

    await middleware.handle(scope, receive, send, downstream)
    stream = iter(chunks)
    await middleware.handle(scope, receive, send, downstream)
    assert calls == 2  # passed through twice — never persisted
    assert responses[0]["status"] == 200


def test_oversized_request_is_rejected_before_buffering() -> None:
    """Reject an over-cap declared body with 413 before buffering."""
    handler, calls = _counting_create()
    config = IdempotencyConfig(max_request_bytes=16)
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        resp = client.post("/create", headers=headers, json={"big": "x" * 64})
        assert resp.status_code == HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert resp.json()["type"].endswith("request-too-large")
        assert calls["n"] == 0


@pytest.mark.anyio
async def test_buffer_request_stops_at_limit_while_streaming() -> None:
    """Stop consuming a streaming body as soon as the cap is exceeded."""
    chunks: list[ReceiveMessage] = [
        {"type": "http.request", "body": b"abcdef", "more_body": True}
    ] * 100
    chunks_iter = iter(chunks)

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return next(chunks_iter)

    _body, _replay, _disc, too_large = await _buffer_request(receive, 8)
    assert too_large
    assert next(chunks_iter, None) is not None  # most chunks were never consumed


@pytest.mark.anyio
async def test_buffer_request_does_not_retain_oversized_chunk() -> None:
    """Drop the over-cap chunk while keeping the replayable prefix."""
    chunks: list[ReceiveMessage] = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"x" * 1024, "more_body": False},
    ]
    chunks_iter = iter(chunks)

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return next(chunks_iter, {"type": "http.disconnect"})

    body, replay, disconnected, too_large = await _buffer_request(receive, 8)
    assert too_large
    assert not disconnected
    assert body == b"ab"
    assert (await replay()).get("body") == b"ab"
    assert (await replay())["type"] == "http.disconnect"


@pytest.mark.anyio
@pytest.mark.parametrize("old_status", [201, 500])
async def test_expired_owner_cannot_finalize_newer_response(old_status: int) -> None:
    """Prevent an expired owner from finalizing a newer reservation."""
    redis = _FakeRedis()
    config = IdempotencyConfig(claim=RedisAtomicClaim(redis))
    original = IdempotencyMiddleware(config)
    newer = IdempotencyMiddleware(config)
    scope = cast("Scope", _raw_scope("/slow", "k"))
    responses: list[Any] = []

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def discard(_message: Message) -> None:
        await asyncio.sleep(0)

    downstream = _ExpiringDownstream(redis, newer, discard, old_status)
    await original.handle(scope, receive, send, downstream)
    responses.clear()
    await newer.handle(scope, receive, send, downstream)
    assert responses[-1]["body"] == b"2"
    assert (b"idempotency-replayed", b"true") in responses[0]["headers"]
    assert downstream.calls == 2


def test_204_replay_omits_content_length() -> None:
    """Omit Content-Length when replaying a 204 response."""

    @post("/gone", status_code=204)
    async def gone() -> None:
        await asyncio.sleep(0)

    with create_test_client(
        route_handlers=[gone], plugins=[IdempotencyPlugin()]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/gone", headers=headers, json={"a": 1})
        replay = client.post("/gone", headers=headers, json={"a": 1})
        assert first.status_code == replay.status_code == 204
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert "content-length" not in replay.headers


def _raw_scope(path: str, key: str) -> dict[str, Any]:
    """Build a minimal ASGI HTTP scope carrying an idempotency key.

    Returns:
        A scope dict shaped like a test-client POST with a JSON body.
    """
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"idempotency-key", key.encode()),
            (b"content-type", b"application/json"),
        ],
        "client": ("testclient", 5000),
        "server": ("testserver", 80),
    }


@pytest.mark.anyio
async def test_delivery_failure_after_full_capture_keeps_the_response() -> None:
    """Persist a fully captured response when delivery fails afterwards."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:

        async def receive() -> ReceiveMessage:
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b'{"a":1}', "more_body": False}

        async def failing_send(message: Message) -> None:
            await asyncio.sleep(0)
            if message["type"] == "http.response.body":
                msg = "client disconnected"
                raise OSError(msg)  # the handler already ran

        with pytest.raises(Exception, match="after response started"):
            await client.app(
                cast("Scope", _raw_scope("/create", "k1")), receive, failing_send
            )
        assert calls["n"] == 1

        retry = client.post("/create", headers={"Idempotency-Key": "k1"}, json={"a": 1})
        assert retry.headers.get(REPLAYED_HEADER) == "true"  # replayed, not re-executed
        assert calls["n"] == 1


@pytest.mark.anyio
async def test_delivery_failure_mid_response_does_not_release_the_claim() -> None:
    """Hold the in-flight marker when delivery fails before capture completes."""
    handler, calls = _counting_create()
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin()]
    ) as client:

        async def receive() -> ReceiveMessage:
            await asyncio.sleep(0)
            return {"type": "http.request", "body": b'{"a":1}', "more_body": False}

        async def failing_send(message: Message) -> None:
            await asyncio.sleep(0)
            if message["type"] == "http.response.start":
                msg = "client disconnected"
                raise OSError(msg)

        with pytest.raises(Exception, match="after response started"):
            await client.app(
                cast("Scope", _raw_scope("/create", "k1")), receive, failing_send
            )

        retry = client.post("/create", headers={"Idempotency-Key": "k1"}, json={"a": 1})
        assert retry.status_code == HTTP_409_CONFLICT  # still in flight, not re-run
        assert calls["n"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("cancel_at", ["send", "persist"])
async def test_cancellation_finalizes_captured_response(cancel_at: str) -> None:
    """Shield finalization from (repeated) cancellation, then report it."""
    send_started = asyncio.Event()
    claim = _SlowClaim()
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=claim))
    scope = cast("Scope", _raw_scope("/cancel", "k"))
    calls = 0
    replay: list[Any] = []
    receive = _canned_body_receive

    async def send(message: Message) -> None:
        if message["type"] == "http.response.body" and cancel_at == "send":
            send_started.set()
            await asyncio.Event().wait()

    async def collect(message: Message) -> None:
        await asyncio.sleep(0)
        replay.append(message)

    async def downstream(_scope: Scope, _receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        await send({"type": "http.response.start", "status": 201, "headers": []})
        await send({"type": "http.response.body", "body": b"done", "more_body": False})

    scenario = _CancelScenario(
        middleware, scope, receive, send, downstream, cancel_at, send_started, claim
    )
    await scenario.run()
    await middleware.handle(scope, receive, collect, downstream)
    assert calls == 1
    assert replay[-1]["body"] == b"done"
    assert (b"idempotency-replayed", b"true") in replay[0]["headers"]


@pytest.mark.anyio
async def test_optional_asgi_response_fields_are_replayed() -> None:
    """Replay responses that omit optional ASGI message fields."""
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=_DictClaim()))
    scope = cast("Scope", _raw_scope("/empty", "k"))
    responses: list[Any] = []
    calls = 0

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def downstream(_scope: Scope, _receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        await send(cast("Message", {"type": "http.response.start", "status": 204}))
        await send(cast("Message", {"type": "http.response.body"}))

    await middleware.handle(scope, receive, send, downstream)
    responses.clear()
    await middleware.handle(scope, receive, send, downstream)
    assert calls == 1
    assert responses[0]["status"] == 204
    assert responses[-1]["body"] == b""
    assert (b"idempotency-replayed", b"true") in responses[0]["headers"]


@pytest.mark.anyio
async def test_cancellation_before_response_keeps_reservation() -> None:
    """Leave the reservation to expire when cancelled before any response."""
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=_DictClaim()))
    scope = cast("Scope", _raw_scope("/cancel", "k"))
    responses: list[Any] = []
    calls = 0

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def downstream(_scope: Scope, _receive: Receive, _send: Send) -> None:
        nonlocal calls
        calls += 1  # represents a side effect before response headers are emitted
        await asyncio.sleep(0)
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await middleware.handle(scope, receive, send, downstream)
    await middleware.handle(scope, receive, send, downstream)
    assert calls == 1
    assert responses[0]["status"] == HTTP_409_CONFLICT


@pytest.mark.anyio
async def test_responses_with_trailers_are_not_cached() -> None:
    """Serve (not cache) responses declaring ASGI trailers, with metadata intact."""
    middleware = IdempotencyMiddleware(IdempotencyConfig(claim=_DictClaim()))
    scope = cast("Scope", _raw_scope("/trailers", "k"))
    responses: list[Any] = []
    calls = 0

    async def receive() -> ReceiveMessage:
        await asyncio.sleep(0)
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Message) -> None:
        await asyncio.sleep(0)
        responses.append(message)

    async def downstream(_scope: Scope, _receive: Receive, send: Send) -> None:
        nonlocal calls
        calls += 1
        await send(
            cast(
                "Message",
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                    "trailers": True,
                },
            )
        )
        await send({"type": "http.response.body", "body": b"done", "more_body": False})
        await send(
            cast(
                "Message",
                {
                    "type": "http.response.trailers",
                    "headers": [(b"digest", b"sha-256=value")],
                },
            )
        )

    for _ in range(2):
        responses.clear()
        await middleware.handle(scope, receive, send, downstream)
        assert responses[0]["trailers"] is True
        assert responses[-1]["type"] == "http.response.trailers"
        assert responses[-1]["headers"] == [(b"digest", b"sha-256=value")]
    assert calls == 2

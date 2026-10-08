"""Tests for the idempotency battery."""

from typing import Any, cast

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

from litestar_batteries import IdempotencyConfig, IdempotencyPlugin, RedisAtomicClaim
from litestar_batteries.idempotency.middleware import (
    IdempotencyMiddleware,
    _buffer_request,  # pyright: ignore[reportPrivateUsage]
    store_key,
)
from litestar_batteries.idempotency.models import StoredResponse

PROBLEM_JSON = "application/problem+json"


class _DictClaim:
    """In-memory AtomicClaim double for exercising the claim code path."""

    def __init__(self) -> None:
        self._data: dict[str, bytes] = {}

    async def claim(self, key: str, value: bytes, *, ttl: int) -> bytes | None:
        if key in self._data:
            return self._data[key]
        self._data[key] = value
        return None

    async def set(self, key: str, value: bytes, *, expected: bytes, ttl: int) -> bool:
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
        name, expected = str(args[0]), args[1]
        if self.store.get(name) != expected:
            return 0
        if len(args) == 2:
            return await self.delete(name)
        self.store[name] = cast("bytes", args[2])
        return 1


REPLAYED_HEADER = "Idempotency-Replayed"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _counting_create() -> Any:
    """A POST handler that counts invocations and echoes its body."""
    calls = {"n": 0}

    @post("/create")
    async def create(data: dict[str, Any]) -> dict[str, Any]:
        calls["n"] += 1
        return {"n": calls["n"], "echo": data}

    create.calls = calls  # type: ignore[attr-defined]
    return create


def test_no_key_passes_through() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        r1 = client.post("/create", json={"a": 1})
        r2 = client.post("/create", json={"a": 1})
        assert r1.status_code == r2.status_code == HTTP_201_CREATED
        assert handler.calls["n"] == 2  # ran both times — no dedupe without a key


def test_get_is_not_deduplicated() -> None:
    calls = {"n": 0}

    @get("/ping")
    async def ping() -> dict[str, int]:
        calls["n"] += 1
        return {"n": calls["n"]}

    with create_test_client(route_handlers=[ping], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k"}
        client.get("/ping", headers=headers)
        client.get("/ping", headers=headers)
        assert calls["n"] == 2  # GET is not a configured method


def test_repeated_key_replays_first_response() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        r1 = client.post("/create", headers=headers, json={"a": 1})
        r2 = client.post("/create", headers=headers, json={"a": 1})
        assert r1.status_code == r2.status_code == HTTP_201_CREATED  # replay preserves status
        assert handler.calls["n"] == 1  # handler ran only once
        assert r1.json() == r2.json()  # identical replayed body
        assert REPLAYED_HEADER not in r1.headers
        assert r2.headers.get(REPLAYED_HEADER) == "true"


def test_same_key_different_body_conflicts() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/create", headers=headers, json={"a": 1})
        assert first.status_code == HTTP_201_CREATED
        reused = client.post("/create", headers=headers, json={"a": 999})
        assert reused.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert handler.calls["n"] == 1  # the mismatched retry did not run the handler


def test_5xx_is_not_cached_and_retry_reruns() -> None:
    calls = {"n": 0}

    @post("/flaky")
    async def flaky(data: dict[str, Any]) -> Response[dict[str, Any]]:
        calls["n"] += 1
        if calls["n"] == 1:
            return Response({"error": "boom"}, status_code=HTTP_500_INTERNAL_SERVER_ERROR)
        return Response({"ok": True}, status_code=HTTP_200_OK)

    with create_test_client(route_handlers=[flaky], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/flaky", headers=headers, json={"a": 1})
        assert first.status_code == HTTP_500_INTERNAL_SERVER_ERROR
        second = client.post("/flaky", headers=headers, json={"a": 1})
        assert second.status_code == HTTP_200_OK  # not replayed — re-ran
        assert calls["n"] == 2


def test_redirect_is_not_cached() -> None:
    # 3xx is not replayable (Location header isn't carried), so it must not be cached.
    calls = {"n": 0}

    @post("/go", status_code=302)
    async def go(data: dict[str, Any]) -> Response[None]:
        calls["n"] += 1
        return Response(None, status_code=302, headers={"Location": "/there"})

    with create_test_client(route_handlers=[go], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/go", headers=headers, json={"a": 1}, follow_redirects=False)
        client.post("/go", headers=headers, json={"a": 1}, follow_redirects=False)
        assert calls["n"] == 2  # re-ran; the redirect was not cached


def test_oversized_response_is_not_cached() -> None:
    calls = {"n": 0}

    @post("/big")
    async def big(data: dict[str, Any]) -> dict[str, str]:
        calls["n"] += 1
        return {"blob": "x" * 5_000}

    config = IdempotencyConfig(max_body_bytes=1_000)  # smaller than the response
    with create_test_client(route_handlers=[big], plugins=[IdempotencyPlugin(config)]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/big", headers=headers, json={"a": 1})
        client.post("/big", headers=headers, json={"a": 1})
        assert calls["n"] == 2  # too large to cache → re-ran


def test_same_key_isolated_across_endpoints() -> None:
    # A ":" in the path must not let one endpoint's key collide with another's.
    calls = {"a": 0, "b": 0}

    @post("/orders:v2")
    async def a(data: dict[str, Any]) -> dict[str, str]:
        calls["a"] += 1
        return {"which": "a"}

    @post("/orders")
    async def b(data: dict[str, Any]) -> dict[str, str]:
        calls["b"] += 1
        return {"which": "b"}

    with create_test_client(route_handlers=[a, b], plugins=[IdempotencyPlugin()]) as client:
        ra = client.post("/orders:v2", headers={"Idempotency-Key": "x"}, json={})
        rb = client.post("/orders", headers={"Idempotency-Key": "v2:x"}, json={})
        assert ra.json() == {"which": "a"}  # not cross-replayed
        assert rb.json() == {"which": "b"}
        assert calls == {"a": 1, "b": 1}


def test_custom_header_and_methods() -> None:
    calls = {"n": 0}

    @post("/put-like")
    async def handler(data: dict[str, Any]) -> dict[str, int]:
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
    handler = _counting_create()
    store = MemoryStore()
    with create_test_client(
        route_handlers=[handler],
        plugins=[IdempotencyPlugin()],
        stores={"idempotency": store},
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        client.post("/create", headers=headers, json={"a": 1})
        assert handler.calls["n"] == 1  # dedupe worked against the provided store


@pytest.mark.anyio
async def test_in_flight_key_returns_409() -> None:
    # Deterministically exercise the in-flight branch: seed the exact record a
    # concurrent, still-processing first request would leave, then fire a retry.
    handler = _counting_create()
    app = Litestar(route_handlers=[handler], plugins=[IdempotencyPlugin()])
    async with AsyncTestClient(app=app) as client:
        store = app.stores.get("idempotency")
        sentinel = StoredResponse(state="processing", request_hash="")
        await store.set(store_key("POST", "/create", "k1"), msgspec.msgpack.encode(sentinel))

        resp = await client.post("/create", headers={"Idempotency-Key": "k1"}, json={"a": 1})
        assert resp.status_code == HTTP_409_CONFLICT
        assert handler.calls["n"] == 0  # the retry did not run the handler


@pytest.mark.anyio
async def test_buffer_request_reassembles_chunked_body() -> None:
    chunks = [
        {"type": "http.request", "body": b"ab", "more_body": True},
        {"type": "http.request", "body": b"cd", "more_body": False},
    ]
    stream = iter(chunks)

    async def receive() -> Any:
        return next(stream)

    body, replay, disconnected, _big = await _buffer_request(receive)
    assert body == b"abcd"  # chunks reassembled for fingerprinting
    assert not disconnected
    assert cast("dict[str, Any]", await replay())["body"] == b"ab"  # replayed verbatim to the app
    assert cast("dict[str, Any]", await replay())["body"] == b"cd"


@pytest.mark.anyio
async def test_buffer_request_flags_disconnect() -> None:
    async def receive() -> Any:
        return {"type": "http.disconnect"}

    body, _replay, disconnected, _big = await _buffer_request(receive)
    assert body == b""
    assert disconnected


def test_scope_isolates_same_key_across_callers() -> None:
    handler = _counting_create()
    config = IdempotencyConfig(scope=lambda r: r.headers.get("X-User", "anon"))
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        key = {"Idempotency-Key": "k"}
        client.post("/create", headers={**key, "X-User": "alice"}, json={"a": 1})
        client.post("/create", headers={**key, "X-User": "bob"}, json={"a": 1})
        assert handler.calls["n"] == 2  # same key, different scope -> not cross-replayed
        client.post("/create", headers={**key, "X-User": "alice"}, json={"a": 1})
        assert handler.calls["n"] == 2  # alice's repeat -> replayed


def test_require_key_rejects_missing_key() -> None:
    handler = _counting_create()
    config = IdempotencyConfig(require_key=True)
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        resp = client.post("/create", json={"a": 1})
        assert resp.status_code == HTTP_400_BAD_REQUEST
        assert resp.headers["content-type"].startswith(PROBLEM_JSON)
        assert resp.json()["type"].endswith("missing-key")
        assert handler.calls["n"] == 0


def test_invalid_key_is_rejected() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        resp = client.post("/create", headers={"Idempotency-Key": "x" * 300}, json={"a": 1})
        assert resp.status_code == HTTP_400_BAD_REQUEST
        assert resp.json()["type"].endswith("invalid-key")
        assert handler.calls["n"] == 0


def test_error_responses_are_problem_json() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        mismatch = client.post("/create", headers=headers, json={"a": 2})
        assert mismatch.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert mismatch.headers["content-type"].startswith(PROBLEM_JSON)
        body = mismatch.json()
        assert body["type"].endswith("payload-mismatch")
        assert body["status"] == HTTP_422_UNPROCESSABLE_ENTITY


def test_replays_allowlisted_headers_only() -> None:
    @post("/make")
    async def make(data: dict[str, Any]) -> Response[dict[str, bool]]:
        return Response({"ok": True}, headers={"ETag": '"abc"', "Set-Cookie": "sid=1"})

    with create_test_client(route_handlers=[make], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/make", headers=headers, json={"a": 1})
        replay = client.post("/make", headers=headers, json={"a": 1})
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert replay.headers.get("ETag") == '"abc"'  # allow-listed → replayed
        assert "set-cookie" not in replay.headers  # denied → not replayed


def test_dedupe_via_atomic_claim_backend() -> None:
    handler = _counting_create()
    config = IdempotencyConfig(claim=_DictClaim())
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create", headers=headers, json={"a": 1})
        replay = client.post("/create", headers=headers, json={"a": 1})
        assert handler.calls["n"] == 1  # deduped through the claim backend
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        mismatch = client.post("/create", headers=headers, json={"a": 2})
        assert mismatch.status_code == HTTP_422_UNPROCESSABLE_ENTITY


@pytest.mark.anyio
async def test_redis_atomic_claim() -> None:
    redis = _FakeRedis()
    claim = RedisAtomicClaim(redis, prefix="idem:")
    assert await claim.claim("k", b"first", ttl=10) is None  # won the reservation
    assert await claim.claim("k", b"second", ttl=10) == b"first"  # lost → incumbent bytes
    assert not await claim.set("k", b"wrong", expected=b"other", ttl=10)
    assert not await claim.delete("k", expected=b"other")
    assert await claim.set("k", b"done", expected=b"first", ttl=10)
    assert redis.store["idem:k"] == b"done"
    assert await claim.delete("k", expected=b"done")
    assert "idem:k" not in redis.store


def test_same_key_different_query_string_conflicts() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/create?action=create", headers=headers, json={"a": 1})
        other = client.post("/create?action=cancel", headers=headers, json={"a": 1})
        assert other.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert handler.calls["n"] == 1


@pytest.mark.parametrize(
    ("status", "header", "value"),
    [
        (401, "WWW-Authenticate", "Basic"),
        (405, "Allow", "POST"),
        (407, "Proxy-Authenticate", "Basic"),
        (429, "Retry-After", "30"),
    ],
)
def test_replays_required_4xx_headers(status: int, header: str, value: str) -> None:
    @post("/limited")
    async def limited(data: dict[str, Any]) -> Response[dict[str, bool]]:
        return Response({"ok": False}, status_code=status, headers={header: value})

    with create_test_client(route_handlers=[limited], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        client.post("/limited", headers=headers, json={"a": 1})
        replay = client.post("/limited", headers=headers, json={"a": 1})
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert replay.status_code == status
        assert replay.headers.get(header) == value


@pytest.mark.anyio
async def test_redis_claim_retries_when_incumbent_vanishes() -> None:
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
    assert await claim.claim("k", b"mine", ttl=10) is None  # re-acquired, not a phantom win
    assert redis.store["idempotency:k"] == b"mine"
    assert await claim.claim("k", b"other", ttl=10) == b"mine"


def test_oversized_request_is_rejected_before_buffering() -> None:
    handler = _counting_create()
    config = IdempotencyConfig(max_request_bytes=16)
    with create_test_client(
        route_handlers=[handler], plugins=[IdempotencyPlugin(config)]
    ) as client:
        headers = {"Idempotency-Key": "k1"}
        resp = client.post("/create", headers=headers, json={"big": "x" * 64})
        assert resp.status_code == HTTP_413_REQUEST_ENTITY_TOO_LARGE
        assert resp.json()["type"].endswith("request-too-large")
        assert handler.calls["n"] == 0


@pytest.mark.anyio
async def test_buffer_request_stops_at_limit_while_streaming() -> None:
    chunks = iter([{"type": "http.request", "body": b"abcdef", "more_body": True}] * 100)

    async def receive() -> Any:
        return next(chunks)

    _body, _replay, _disc, too_large = await _buffer_request(receive, 8)
    assert too_large
    assert next(chunks, None) is not None  # most chunks were never consumed


@pytest.mark.anyio
async def test_buffer_request_does_not_retain_oversized_chunk() -> None:
    chunks = iter(
        [
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"x" * 1024, "more_body": False},
        ]
    )

    async def receive() -> Any:
        return next(chunks)

    body, replay, disconnected, too_large = await _buffer_request(receive, 8)
    assert too_large and not disconnected
    assert body == b"ab"
    assert (await replay()).get("body") == b"ab"
    assert (await replay()).get("body") == b""


@pytest.mark.anyio
@pytest.mark.parametrize("old_status", [201, 500])
async def test_expired_owner_cannot_finalize_newer_response(old_status: int) -> None:
    redis = _FakeRedis()
    calls = 0
    config = IdempotencyConfig(claim=RedisAtomicClaim(redis))
    original = IdempotencyMiddleware(config)
    newer = IdempotencyMiddleware(config)
    scope = cast("Any", _raw_scope("/slow", "k"))
    responses: list[Any] = []

    async def receive() -> Any:
        return {"type": "http.request", "body": b"{}", "more_body": False}

    async def send(message: Any) -> None:
        responses.append(message)

    async def discard(message: Any) -> None:
        pass

    async def downstream(scope: Any, receive: Any, send: Any) -> None:
        nonlocal calls
        calls += 1
        invocation = calls
        if invocation == 1:
            redis.store.clear()  # lease expires before the original handler finishes
            await newer.handle(scope, receive, discard, downstream)
        await send(
            {
                "type": "http.response.start",
                "status": old_status if invocation == 1 else 201,
                "headers": [],
            }
        )
        await send(
            {"type": "http.response.body", "body": str(invocation).encode(), "more_body": False}
        )

    await original.handle(scope, receive, send, downstream)
    responses.clear()
    await newer.handle(scope, receive, send, downstream)
    assert responses[-1]["body"] == b"2"
    assert (b"idempotency-replayed", b"true") in responses[0]["headers"]
    assert calls == 2


def test_204_replay_omits_content_length() -> None:
    @post("/gone", status_code=204)
    async def gone(data: dict[str, Any]) -> None:
        return None

    with create_test_client(route_handlers=[gone], plugins=[IdempotencyPlugin()]) as client:
        headers = {"Idempotency-Key": "k1"}
        first = client.post("/gone", headers=headers, json={"a": 1})
        replay = client.post("/gone", headers=headers, json={"a": 1})
        assert first.status_code == replay.status_code == 204
        assert replay.headers.get(REPLAYED_HEADER) == "true"
        assert "content-length" not in replay.headers


def _raw_scope(path: str, key: str) -> dict[str, Any]:
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
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        sent = False

        async def receive() -> Any:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": b'{"a":1}', "more_body": False}

        async def failing_send(message: Any) -> None:
            if message["type"] == "http.response.body":
                raise OSError("client disconnected")  # the handler already ran

        with pytest.raises(Exception, match="after response started"):
            await client.app(_raw_scope("/create", "k1"), receive, failing_send)
        assert handler.calls["n"] == 1

        retry = client.post("/create", headers={"Idempotency-Key": "k1"}, json={"a": 1})
        assert retry.headers.get(REPLAYED_HEADER) == "true"  # replayed, not re-executed
        assert handler.calls["n"] == 1


@pytest.mark.anyio
async def test_delivery_failure_mid_response_does_not_release_the_claim() -> None:
    handler = _counting_create()
    with create_test_client(route_handlers=[handler], plugins=[IdempotencyPlugin()]) as client:
        sent = False

        async def receive() -> Any:
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": b'{"a":1}', "more_body": False}

        async def failing_send(message: Any) -> None:
            if message["type"] == "http.response.start":
                raise OSError("client disconnected")

        with pytest.raises(Exception, match="after response started"):
            await client.app(_raw_scope("/create", "k1"), receive, failing_send)

        retry = client.post("/create", headers={"Idempotency-Key": "k1"}, json={"a": 1})
        assert retry.status_code == HTTP_409_CONFLICT  # still in flight, not re-run
        assert handler.calls["n"] == 1

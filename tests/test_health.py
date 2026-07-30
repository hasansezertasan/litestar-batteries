"""Tests for the health-check battery."""

import asyncio

from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE
from litestar.testing import create_test_client

from litestar_batteries import HealthCheck, HealthConfig, HealthPlugin


async def _ok() -> None:
    return None


async def _fail() -> None:
    raise RuntimeError("db down")


async def _slow() -> None:
    await asyncio.sleep(0.2)


async def _raise_timeout() -> None:
    # A check whose own dependency (db/http client) timed out, surfaced as
    # asyncio.TimeoutError — the SAME type wait_for raises for its deadline, so
    # the readiness handler must not conflate the two. (On 3.10 asyncio.TimeoutError
    # is distinct from builtin TimeoutError; raise the exact type to be version-proof.)
    raise asyncio.TimeoutError("upstream db timeout")


def test_liveness_always_ok() -> None:
    with create_test_client(route_handlers=[], plugins=[HealthPlugin()]) as client:
        resp = client.get("/health")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_readiness_all_pass() -> None:
    config = HealthConfig(checks=[HealthCheck("a", _ok), HealthCheck("b", _ok)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        body = resp.json()
        assert body["status"] == "ok"
        assert {c["name"]: c["status"] for c in body["checks"]} == {"a": "ok", "b": "ok"}


def test_readiness_one_fails_returns_503() -> None:
    config = HealthConfig(checks=[HealthCheck("a", _ok), HealthCheck("db", _fail)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_503_SERVICE_UNAVAILABLE
        body = resp.json()
        assert body["status"] == "error"
        db = next(c for c in body["checks"] if c["name"] == "db")
        assert db["status"] == "error"
        assert "db down" in db["error"]


def test_readiness_no_checks_ok() -> None:
    with create_test_client(route_handlers=[], plugins=[HealthPlugin()]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_readiness_check_timeout_returns_503() -> None:
    config = HealthConfig(checks=[HealthCheck("slow", _slow, timeout=0.01)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_503_SERVICE_UNAVAILABLE
        body = resp.json()
        assert body["status"] == "error"
        slow = next(c for c in body["checks"] if c["name"] == "slow")
        assert slow["status"] == "error"
        assert "timed out" in slow["error"]


def test_readiness_timeout_none_is_unbounded() -> None:
    # A slow check with the default timeout=None still passes: no time bound is
    # applied, so it must not be cut short (would fail if a finite default crept in).
    config = HealthConfig(checks=[HealthCheck("slow", _slow)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_readiness_check_own_timeout_error_kept_unbounded() -> None:
    # timeout=None: a TimeoutError raised BY the check is its real failure,
    # not the wrapper deadline — surface its message, not "timed out after Nones".
    config = HealthConfig(checks=[HealthCheck("db", _raise_timeout)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_503_SERVICE_UNAVAILABLE
        db = next(c for c in resp.json()["checks"] if c["name"] == "db")
        assert db["status"] == "error"
        assert "upstream db timeout" in db["error"]
        assert "timed out after" not in db["error"]


def test_readiness_check_own_timeout_error_kept_bounded() -> None:
    # Finite timeout: a check that raises its OWN TimeoutError immediately (well
    # within budget) must surface its real error, not the wrapper deadline.
    config = HealthConfig(checks=[HealthCheck("db", _raise_timeout, timeout=5.0)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_503_SERVICE_UNAVAILABLE
        db = next(c for c in resp.json()["checks"] if c["name"] == "db")
        assert "upstream db timeout" in db["error"]
        assert "timed out after" not in db["error"]


def test_readiness_within_timeout_passes() -> None:
    # Fast check with a generous timeout completes well within budget -> 200.
    config = HealthConfig(checks=[HealthCheck("fast", _ok, timeout=5.0)])
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        resp = client.get("/health/ready")
        assert resp.status_code == HTTP_200_OK
        assert resp.json()["status"] == "ok"


def test_custom_path() -> None:
    config = HealthConfig(path="/healthz")
    with create_test_client(route_handlers=[], plugins=[HealthPlugin(config)]) as client:
        assert client.get("/healthz").status_code == HTTP_200_OK

"""Tests for the secure-headers battery."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, cast

import pytest
from litestar import Litestar, Response, get
from litestar.datastructures import MutableScopeHeaders
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_404_NOT_FOUND,
    HTTP_405_METHOD_NOT_ALLOWED,
    HTTP_500_INTERNAL_SERVER_ERROR,
)
from litestar.testing import create_test_client

from litestar_batteries import SecureHeadersConfig, SecureHeadersPlugin
from litestar_batteries.secure_headers.hooks import build_before_send
from litestar_batteries.secure_headers.models import _hsts_value, _response_headers

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from litestar.testing import TestClient
    from litestar.types import Message, Scope

DEFAULT_CSP = (
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
HSTS_YEAR = 31_536_000


def test_defaults() -> None:
    """The default config matches the documented secure baseline."""
    config = SecureHeadersConfig()
    assert config.hsts_max_age == HSTS_YEAR
    assert config.hsts_include_subdomains is False
    assert config.hsts_preload is False
    assert config.content_type_options is True
    assert config.frame_options == "DENY"
    assert config.content_security_policy == DEFAULT_CSP
    assert config.content_security_policy_report_only is None
    assert config.referrer_policy == "strict-origin-when-cross-origin"
    assert config.permissions_policy == "camera=(), microphone=(), geolocation=()"
    assert config.cross_origin_opener_policy == "same-origin"
    assert config.cross_origin_resource_policy is None
    assert config.cross_origin_embedder_policy is None
    assert config.permitted_cross_domain_policies == "none"
    assert config.override is False


def test_response_headers_defaults() -> None:
    """Default static headers are lowercase pairs and never include X-XSS-Protection."""
    assert _response_headers(SecureHeadersConfig()) == (
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("content-security-policy", DEFAULT_CSP),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
        ("cross-origin-opener-policy", "same-origin"),
        ("x-permitted-cross-domain-policies", "none"),
    )


@pytest.mark.parametrize(
    ("field", "header"),
    [
        ("content_type_options", "x-content-type-options"),
        ("frame_options", "x-frame-options"),
        ("content_security_policy", "content-security-policy"),
        ("referrer_policy", "referrer-policy"),
        ("permissions_policy", "permissions-policy"),
        ("cross_origin_opener_policy", "cross-origin-opener-policy"),
        ("permitted_cross_domain_policies", "x-permitted-cross-domain-policies"),
    ],
)
def test_disabled_fields_are_omitted(field: str, header: str) -> None:
    """Setting a default-on header's field to off removes only that header."""
    off = False if field == "content_type_options" else None
    kwargs: dict[str, Any] = {field: off}
    config = SecureHeadersConfig(**kwargs)
    names = [name for name, _ in _response_headers(config)]
    assert header not in names
    assert len(names) == len(_response_headers(SecureHeadersConfig())) - 1


def test_opt_in_headers_are_emitted() -> None:
    """Default-off headers appear once configured."""
    config = SecureHeadersConfig(
        content_security_policy_report_only="default-src 'self'",
        cross_origin_resource_policy="same-site",
        cross_origin_embedder_policy="require-corp",
    )
    headers = dict(_response_headers(config))
    assert headers["content-security-policy-report-only"] == "default-src 'self'"
    assert headers["cross-origin-resource-policy"] == "same-site"
    assert headers["cross-origin-embedder-policy"] == "require-corp"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "max-age=31536000"),
        ({"hsts_max_age": 60}, "max-age=60"),
        ({"hsts_include_subdomains": True}, "max-age=31536000; includeSubDomains"),
        (
            {"hsts_include_subdomains": True, "hsts_preload": True},
            "max-age=31536000; includeSubDomains; preload",
        ),
        ({"hsts_max_age": None}, None),
    ],
)
def test_hsts_value(kwargs: dict[str, Any], expected: str | None) -> None:
    """The HSTS directive string is assembled from its parts."""
    assert _hsts_value(SecureHeadersConfig(**kwargs)) == expected


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"referrer_policy": "no-referrer\r\nX-Evil: 1"}, "control characters"),
        ({"content_security_policy": "default-src 'self'\n"}, "control characters"),
        ({"permissions_policy": "a\x00b"}, "control characters"),
        ({"permissions_policy": "geolocation=(\u20ac)"}, "latin-1"),
        ({"hsts_max_age": -1}, "negative"),
        ({"hsts_preload": True}, "hsts_preload needs"),
        (
            {"hsts_preload": True, "hsts_include_subdomains": True, "hsts_max_age": 60},
            "hsts_preload needs",
        ),
        (
            {"hsts_max_age": None, "hsts_include_subdomains": True},
            "require hsts_max_age",
        ),
        ({"hsts_max_age": None, "hsts_preload": True}, "require hsts_max_age"),
    ],
)
def test_invalid_config_rejected(kwargs: dict[str, Any], message: str) -> None:
    """Unsafe or inconsistent configuration fails at construction."""
    with pytest.raises(ValueError, match=message):
        SecureHeadersConfig(**kwargs)


async def _send(
    hook: Callable[[Message, Scope], Awaitable[None]],
    message: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    await hook(cast("Message", message), cast("Scope", scope))


def _start(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {"type": "http.response.start", "status": 200, "headers": headers or []}


def _names(message: dict[str, Any]) -> dict[bytes, bytes]:
    return dict(message["headers"])


@pytest.mark.anyio
async def test_hook_adds_default_headers() -> None:
    """Every enabled static header is added to the response start."""
    hook = build_before_send(SecureHeadersConfig())
    message = _start()
    await _send(hook, message, {"type": "http", "scheme": "http"})
    expected = {
        name.encode(): value.encode()
        for name, value in _response_headers(SecureHeadersConfig())
    }
    assert _names(message) == expected


@pytest.mark.anyio
async def test_hook_handler_header_wins_by_default() -> None:
    """A header the handler already set is left alone, case-insensitively."""
    hook = build_before_send(SecureHeadersConfig())
    message = _start([(b"Content-Security-Policy", b"custom")])
    await _send(hook, message, {"type": "http", "scheme": "http"})
    values = [
        v for k, v in message["headers"] if k.lower() == b"content-security-policy"
    ]
    assert values == [b"custom"]


@pytest.mark.parametrize(
    ("scheme", "config", "expected"),
    [
        ("https", SecureHeadersConfig(), b"max-age=31536000"),
        ("http", SecureHeadersConfig(), None),
        ("https", SecureHeadersConfig(hsts_max_age=None), None),
        (
            "https",
            SecureHeadersConfig(hsts_include_subdomains=True, hsts_preload=True),
            b"max-age=31536000; includeSubDomains; preload",
        ),
    ],
)
@pytest.mark.anyio
async def test_hook_hsts_only_over_https(
    scheme: str, config: SecureHeadersConfig, expected: bytes | None
) -> None:
    """HSTS is emitted only for HTTPS requests and only when enabled."""
    hook = build_before_send(config)
    message = _start()
    await _send(hook, message, {"type": "http", "scheme": scheme})
    assert _names(message).get(b"strict-transport-security") == expected


@pytest.mark.parametrize(
    "message",
    [
        {"type": "http.response.body", "body": b"x", "more_body": False},
        {"type": "websocket.accept", "headers": []},
    ],
)
@pytest.mark.anyio
async def test_hook_ignores_other_messages(message: dict[str, Any]) -> None:
    """Only ``http.response.start`` is modified."""
    before = {k: list(v) if isinstance(v, list) else v for k, v in message.items()}
    hook = build_before_send(SecureHeadersConfig())
    await _send(hook, message, {"type": "http", "scheme": "https"})
    assert message == before


def _client(
    *handlers: Any,  # noqa: ANN401
    config: SecureHeadersConfig | None = None,
    base_url: str = "http://testserver.local",
    **app_kwargs: Any,  # noqa: ANN401
) -> TestClient[Litestar]:
    return create_test_client(
        list(handlers),
        plugins=[SecureHeadersPlugin(config)],
        base_url=base_url,
        **app_kwargs,
    )


@get("/ok", sync_to_thread=False)
def _ok() -> str:
    return "ok"


@get("/boom", sync_to_thread=False)
def _boom() -> str:
    msg = "boom"
    raise RuntimeError(msg)


@get("/custom", sync_to_thread=False)
def _custom() -> Response[str]:
    return Response("x", headers={"Content-Security-Policy": "custom"})


def test_plugin_default_config() -> None:
    """The plugin defaults to ``SecureHeadersConfig()``."""
    assert SecureHeadersPlugin().config == SecureHeadersConfig()


def test_plugin_headers_on_success_and_hsts_scheme() -> None:
    """A 200 carries the defaults; HSTS appears only over HTTPS."""
    with _client(_ok) as client:
        response = client.get("/ok")
        assert response.status_code == HTTP_200_OK
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-security-policy"] == DEFAULT_CSP
        assert "strict-transport-security" not in response.headers
    with _client(_ok, base_url="https://testserver.local") as client:
        assert client.get("/ok").headers["strict-transport-security"] == (
            "max-age=31536000"
        )


def test_plugin_headers_on_router_errors() -> None:
    """Router-level 404 and 405 responses are covered (route middleware misses them)."""
    with _client(_ok) as client:
        not_found = client.get("/missing")
        wrong_method = client.post("/ok")
    assert not_found.status_code == HTTP_404_NOT_FOUND
    assert wrong_method.status_code == HTTP_405_METHOD_NOT_ALLOWED
    for response in (not_found, wrong_method):
        assert response.headers["x-frame-options"] == "DENY"


def test_plugin_headers_on_unhandled_exception() -> None:
    """A handler crash (500) still carries the headers."""
    with _client(_boom) as client:
        response = client.get("/boom")
    assert response.status_code == HTTP_500_INTERNAL_SERVER_ERROR
    assert response.headers["x-content-type-options"] == "nosniff"


def test_plugin_handler_header_wins_unless_override() -> None:
    """Handler-set CSP survives by default and is replaced with ``override``."""
    with _client(_custom) as client:
        assert client.get("/custom").headers["content-security-policy"] == "custom"
    with _client(_custom, config=SecureHeadersConfig(override=True)) as client:
        assert client.get("/custom").headers["content-security-policy"] == DEFAULT_CSP


def test_plugin_per_field_overrides() -> None:
    """Fields can be changed or disabled individually."""
    config = SecureHeadersConfig(frame_options=None, referrer_policy="no-referrer")
    with _client(_ok, config=config) as client:
        response = client.get("/ok")
    assert "x-frame-options" not in response.headers
    assert response.headers["referrer-policy"] == "no-referrer"


def test_plugin_preserves_user_before_send_hook() -> None:
    """A user-registered ``before_send`` hook still runs alongside the plugin."""

    def stamp(message: Message, scope: Scope) -> None:  # noqa: ARG001
        if message["type"] == "http.response.start":
            MutableScopeHeaders.from_message(message)["x-user-hook"] = "1"

    with _client(_ok, before_send=[stamp]) as client:
        response = client.get("/ok")
    assert response.headers["x-user-hook"] == "1"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_plugin_openapi_ui_served_with_default_policy() -> None:
    """The default CSP leaves the OpenAPI UI usable (no script/default-src)."""
    with _client(_ok) as client:
        response = client.get("/schema/swagger")
    assert response.status_code == HTTP_200_OK
    csp = response.headers["content-security-policy"]
    assert "script-src" not in csp
    assert "default-src" not in csp


def test_app_without_plugin_has_no_security_headers() -> None:
    """Not registering the plugin changes nothing."""
    with create_test_client([_ok]) as client:
        assert "x-content-type-options" not in client.get("/ok").headers


@pytest.mark.anyio
async def test_hook_override_replaces_three_duplicate_headers() -> None:
    """``override`` leaves exactly one value even if the handler set several."""
    hook = build_before_send(SecureHeadersConfig(override=True))
    message = _start([(b"content-security-policy", b"a")] * 3)
    await _send(hook, message, {"type": "http", "scheme": "http"})
    values = [v for k, v in message["headers"] if k == b"content-security-policy"]
    assert values == [DEFAULT_CSP.encode()]


@pytest.mark.anyio
async def test_hook_override_applies_to_hsts() -> None:
    """``override`` also replaces a handler-set HSTS header over HTTPS."""
    hook = build_before_send(SecureHeadersConfig(override=True))
    message = _start([(b"strict-transport-security", b"max-age=1")])
    await _send(hook, message, {"type": "http", "scheme": "https"})
    assert _names(message)[b"strict-transport-security"] == b"max-age=31536000"


def test_hook_is_coroutine_function() -> None:
    """The hook is async so Litestar does not thread-dispatch every message."""
    assert inspect.iscoroutinefunction(build_before_send(SecureHeadersConfig()))


def test_empty_string_disables_header() -> None:
    """An empty value omits the header, like ``None``."""
    names = [n for n, _ in _response_headers(SecureHeadersConfig(referrer_policy=""))]
    assert "referrer-policy" not in names


@pytest.mark.parametrize("override", [False, True])
def test_plugin_ordering_with_user_hook_setting_csp(*, override: bool) -> None:
    """A user hook running first keeps its CSP unless ``override`` is set."""

    def user_csp(message: Message, scope: Scope) -> None:  # noqa: ARG001
        if message["type"] == "http.response.start":
            MutableScopeHeaders.from_message(message)["content-security-policy"] = (
                "user"
            )

    config = SecureHeadersConfig(override=override)
    with _client(_ok, config=config, before_send=[user_csp]) as client:
        csp = client.get("/ok").headers["content-security-policy"]
    assert csp == (DEFAULT_CSP if override else "user")


@pytest.mark.anyio
async def test_hook_handles_start_message_without_headers() -> None:
    """ASGI makes ``headers`` optional; a bare start message still gets headers."""
    hook = build_before_send(SecureHeadersConfig())
    message: dict[str, Any] = {"type": "http.response.start", "status": 200}
    await _send(hook, message, {"type": "http", "scheme": "http"})
    assert _names(message)[b"x-content-type-options"] == b"nosniff"

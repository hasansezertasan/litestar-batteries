"""Tests for the secure-headers battery."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from litestar_batteries.secure_headers.hooks import build_before_send
from litestar_batteries.secure_headers.models import SecureHeadersConfig

if TYPE_CHECKING:
    from collections.abc import Callable

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
    assert SecureHeadersConfig().response_headers() == (
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
    names = [name for name, _ in config.response_headers()]
    assert header not in names
    assert len(names) == len(SecureHeadersConfig().response_headers()) - 1


def test_opt_in_headers_are_emitted() -> None:
    """Default-off headers appear once configured."""
    config = SecureHeadersConfig(
        content_security_policy_report_only="default-src 'self'",
        cross_origin_resource_policy="same-site",
        cross_origin_embedder_policy="require-corp",
    )
    headers = dict(config.response_headers())
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
    assert SecureHeadersConfig(**kwargs).hsts_value() == expected


@pytest.mark.parametrize(
    "kwargs",
    [
        {"referrer_policy": "no-referrer\r\nX-Evil: 1"},
        {"content_security_policy": "default-src 'self'\n"},
        {"permissions_policy": "geolocation=(€)"},
        {"hsts_max_age": -1},
        {"hsts_preload": True},
        {"hsts_preload": True, "hsts_include_subdomains": True, "hsts_max_age": 60},
        {"hsts_max_age": None, "hsts_include_subdomains": True},
        {"hsts_max_age": None, "hsts_preload": True},
    ],
)
def test_invalid_config_rejected(kwargs: dict[str, Any]) -> None:
    """Unsafe or inconsistent configuration fails at construction."""
    with pytest.raises(ValueError, match=r"."):
        SecureHeadersConfig(**kwargs)


def _send(
    hook: Callable[[Message, Scope], None],
    message: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    hook(cast("Message", message), cast("Scope", scope))


def _start(headers: list[tuple[bytes, bytes]] | None = None) -> dict[str, Any]:
    return {"type": "http.response.start", "status": 200, "headers": headers or []}


def _names(message: dict[str, Any]) -> dict[bytes, bytes]:
    return dict(message["headers"])


def test_hook_adds_default_headers() -> None:
    """Every enabled static header is added to the response start."""
    hook = build_before_send(SecureHeadersConfig())
    message = _start()
    _send(hook, message, {"type": "http", "scheme": "http"})
    headers = _names(message)
    assert headers[b"x-content-type-options"] == b"nosniff"
    assert headers[b"content-security-policy"] == DEFAULT_CSP.encode()
    assert b"strict-transport-security" not in headers


def test_hook_handler_header_wins_by_default() -> None:
    """A header the handler already set is left alone, case-insensitively."""
    hook = build_before_send(SecureHeadersConfig())
    message = _start([(b"Content-Security-Policy", b"custom")])
    _send(hook, message, {"type": "http", "scheme": "http"})
    values = [
        v for k, v in message["headers"] if k.lower() == b"content-security-policy"
    ]
    assert values == [b"custom"]


def test_hook_override_replaces_handler_header() -> None:
    """With ``override=True`` the battery's value replaces the handler's."""
    hook = build_before_send(SecureHeadersConfig(override=True))
    message = _start([(b"Content-Security-Policy", b"custom")])
    _send(hook, message, {"type": "http", "scheme": "http"})
    values = [
        v for k, v in message["headers"] if k.lower() == b"content-security-policy"
    ]
    assert values == [DEFAULT_CSP.encode()]


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
def test_hook_hsts_only_over_https(
    scheme: str, config: SecureHeadersConfig, expected: bytes | None
) -> None:
    """HSTS is emitted only for HTTPS requests and only when enabled."""
    hook = build_before_send(config)
    message = _start()
    _send(hook, message, {"type": "http", "scheme": scheme})
    assert _names(message).get(b"strict-transport-security") == expected


@pytest.mark.parametrize(
    "message",
    [
        {"type": "http.response.body", "body": b"x", "more_body": False},
        {"type": "websocket.accept", "headers": []},
    ],
)
def test_hook_ignores_other_messages(message: dict[str, Any]) -> None:
    """Only ``http.response.start`` is modified."""
    before = {k: list(v) if isinstance(v, list) else v for k, v in message.items()}
    hook = build_before_send(SecureHeadersConfig())
    _send(hook, message, {"type": "http", "scheme": "https"})
    assert message == before

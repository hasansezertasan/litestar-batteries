"""Data types for the secure-headers battery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["SecureHeadersConfig"]


DEFAULT_CONTENT_SECURITY_POLICY = (
    "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
)
"""Non-breaking baseline without ``default-src``/``script-src`` (OpenAPI UIs work)."""

DEFAULT_PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"
"""Deny the most sensitive browser features by default."""

_HSTS_PRELOAD_MIN_AGE = 31_536_000


def _check_header_value(field_name: str, value: str | None) -> None:
    """Reject values that cannot be sent safely as one HTTP header line.

    Raises:
        ValueError: If the value has a line break or is not latin-1 encodable.
    """
    if value is None:
        return
    if "\r" in value or "\n" in value:
        msg = f"{field_name} must not contain line breaks"
        raise ValueError(msg)
    try:
        _ = value.encode("latin-1")
    except UnicodeEncodeError as error:
        msg = f"{field_name} must be latin-1 encodable"
        raise ValueError(msg) from error


# Fourteen options describe one user-facing policy surface; grouping them into
# sub-configs would break the documented flat API for no behavioral gain.
@dataclass
class SecureHeadersConfig:  # pylint: disable=too-many-instance-attributes
    """Configuration for :class:`SecureHeadersPlugin`.

    Every header field disables its header when set to ``None`` (or ``False``
    for ``content_type_options``). ``X-XSS-Protection`` is deprecated and is
    intentionally never sent.

    Attributes:
        hsts_max_age: ``Strict-Transport-Security`` max-age in seconds, sent
            only on HTTPS requests. ``None`` disables HSTS.
        hsts_include_subdomains: Add ``includeSubDomains`` to HSTS.
        hsts_preload: Add ``preload`` to HSTS. Requires ``includeSubDomains``
            and a max-age of at least one year.
        content_type_options: Send ``X-Content-Type-Options: nosniff``.
        frame_options: ``X-Frame-Options`` value.
        content_security_policy: ``Content-Security-Policy`` value.
        content_security_policy_report_only: ``Content-Security-Policy-Report-Only``
            value.
        referrer_policy: ``Referrer-Policy`` value.
        permissions_policy: ``Permissions-Policy`` value.
        cross_origin_opener_policy: ``Cross-Origin-Opener-Policy`` value.
        cross_origin_resource_policy: ``Cross-Origin-Resource-Policy`` value.
        cross_origin_embedder_policy: ``Cross-Origin-Embedder-Policy`` value.
        permitted_cross_domain_policies: ``X-Permitted-Cross-Domain-Policies``
            value.
        override: Replace headers a handler already set instead of leaving them.
    """

    hsts_max_age: int | None = _HSTS_PRELOAD_MIN_AGE
    hsts_include_subdomains: bool = False
    hsts_preload: bool = False
    content_type_options: bool = True
    frame_options: Literal["DENY", "SAMEORIGIN"] | None = "DENY"
    content_security_policy: str | None = DEFAULT_CONTENT_SECURITY_POLICY
    content_security_policy_report_only: str | None = None
    referrer_policy: str | None = "strict-origin-when-cross-origin"
    permissions_policy: str | None = DEFAULT_PERMISSIONS_POLICY
    cross_origin_opener_policy: str | None = "same-origin"
    cross_origin_resource_policy: str | None = None
    cross_origin_embedder_policy: str | None = None
    permitted_cross_domain_policies: str | None = "none"
    override: bool = False

    def __post_init__(self) -> None:
        """Validate header values and the HSTS directive combination."""
        for name, value in self.response_headers():
            _check_header_value(name, value)
        self._check_hsts()

    def _check_hsts(self) -> None:
        """Reject inconsistent HSTS settings.

        Raises:
            ValueError: If max-age is negative, a directive is set while HSTS is
                disabled, or ``preload`` lacks its prerequisites.
        """
        if self.hsts_max_age is None:
            if self.hsts_include_subdomains or self.hsts_preload:
                msg = "hsts_include_subdomains and hsts_preload require hsts_max_age"
                raise ValueError(msg)
            return
        if self.hsts_max_age < 0:
            msg = "hsts_max_age must not be negative"
            raise ValueError(msg)
        if self.hsts_preload and not (
            self.hsts_include_subdomains and self.hsts_max_age >= _HSTS_PRELOAD_MIN_AGE
        ):
            msg = "hsts_preload needs hsts_include_subdomains and a 1 year hsts_max_age"
            raise ValueError(msg)

    def response_headers(self) -> tuple[tuple[str, str], ...]:
        """Return the enabled static headers as lowercase ``(name, value)`` pairs.

        Returns:
            The headers sent on every response, excluding HSTS (see
            :meth:`hsts_value`, which is conditional on the request scheme).
        """
        rows = (
            (
                "x-content-type-options",
                "nosniff" if self.content_type_options else None,
            ),
            ("x-frame-options", self.frame_options),
            ("content-security-policy", self.content_security_policy),
            (
                "content-security-policy-report-only",
                self.content_security_policy_report_only,
            ),
            ("referrer-policy", self.referrer_policy),
            ("permissions-policy", self.permissions_policy),
            ("cross-origin-opener-policy", self.cross_origin_opener_policy),
            ("cross-origin-resource-policy", self.cross_origin_resource_policy),
            ("cross-origin-embedder-policy", self.cross_origin_embedder_policy),
            ("x-permitted-cross-domain-policies", self.permitted_cross_domain_policies),
        )
        return tuple((name, value) for name, value in rows if value)

    def hsts_value(self) -> str | None:
        """Return the ``Strict-Transport-Security`` value, or ``None`` if disabled.

        Returns:
            The assembled directive string.
        """
        if self.hsts_max_age is None:
            return None
        directives = [f"max-age={self.hsts_max_age}"]
        if self.hsts_include_subdomains:
            directives.append("includeSubDomains")
        if self.hsts_preload:
            directives.append("preload")
        return "; ".join(directives)

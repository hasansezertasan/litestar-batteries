"""Data types for the idempotency battery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import msgspec

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from typing import Any

    from litestar import Request

    from litestar_batteries.idempotency.claims import AtomicClaim

DEFAULT_HEADER = "Idempotency-Key"
"""Default request header carrying the idempotency key."""

DEFAULT_STORE = "idempotency"
"""Default Litestar store registry name used to persist idempotency records."""

DEFAULT_REPLAY_HEADERS = frozenset(
    {
        "content-type",
        "content-language",
        "content-encoding",
        "cache-control",
        "etag",
        "expires",
        "last-modified",
        "location",
    }
)
"""Response headers stored and replayed by default. Volatile/sensitive headers
(``set-cookie``, ``authorization``, hop-by-hop) are intentionally excluded."""

RecordState = Literal["processing", "done"]
"""Lifecycle of a stored idempotency record."""


class StoredResponse(msgspec.Struct):
    """Persisted record of an in-flight or completed idempotent request.

    A ``processing`` record marks a key whose request is still running (used to
    detect concurrent retries). A ``done`` record carries the captured response
    that is replayed on subsequent retries with the same key and request body.
    """

    state: RecordState
    request_hash: str = ""
    status: int = 0
    # (name, value) pairs, allow-listed; msgspec treats an empty literal as a
    # per-instance factory, so this default is not shared state.
    headers: list[tuple[str, str]] = []
    body: bytes = b""


@dataclass
class IdempotencyConfig:
    """Configuration for :class:`IdempotencyPlugin`.

    ``methods`` and ``header_name`` are matched case-insensitively. ``store`` names
    a Litestar store in ``app.stores`` (a ``MemoryStore`` is created on demand by
    default; map it to a ``RedisStore`` via the app's ``stores=`` argument). ``ttl``
    bounds how long a completed response is replayable.

    ``lock_ttl`` bounds the in-flight marker so a crashed request cannot wedge a
    key forever. **It must exceed the runtime of your slowest handler:** if a
    handler runs longer than ``lock_ttl`` the marker expires mid-flight and a
    concurrent retry will re-run the operation.

    ``max_body_bytes`` caps the response size cached; larger responses are served
    but not stored (buffering short-circuits at the cap, bounding memory). ``None``
    disables the cap.

    ``scope`` isolates keys per caller: it maps a request to a scope string (e.g.
    the authenticated user/tenant id) folded into the store key, so two callers
    using the same key on the same endpoint never replay each other's response.
    ``None`` (default) means a single global scope — set it for any multi-tenant API.

    ``require_key`` rejects a configured-method request that omits the header with
    ``400`` (default: pass such requests through untouched). ``max_key_length`` caps
    the accepted key length (``400`` beyond it; also bounds key-cardinality abuse).

    ``replay_headers`` is the set of response header names (lowercased) that are
    stored and replayed. ``claim`` supplies an :class:`AtomicClaim` for a real
    cross-process in-flight guard; without it the guard is a per-worker lock.
    """

    header_name: str = DEFAULT_HEADER
    methods: Sequence[str] = ("POST", "PATCH")
    store: str = DEFAULT_STORE
    ttl: int = 86_400
    lock_ttl: int = 60
    max_body_bytes: int | None = 1_048_576
    scope: Callable[[Request[Any, Any, Any]], str] | None = None
    require_key: bool = False
    max_key_length: int = 255
    replay_headers: frozenset[str] = DEFAULT_REPLAY_HEADERS
    claim: AtomicClaim | None = None

"""Data types for the idempotency battery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

import msgspec

if TYPE_CHECKING:
    from collections.abc import Sequence

DEFAULT_HEADER = "Idempotency-Key"
"""Default request header carrying the idempotency key."""

DEFAULT_STORE = "idempotency"
"""Default Litestar store registry name used to persist idempotency records."""

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
    media_type: str | None = None
    body: bytes = b""


@dataclass
class IdempotencyConfig:
    """Configuration for :class:`IdempotencyPlugin`.

    ``methods`` and ``header_name`` are matched case-insensitively at request
    time. ``store`` names a Litestar store in ``app.stores`` (a ``MemoryStore``
    is created on demand by default; map it to a ``RedisStore`` via the app's
    ``stores=`` argument to share state across processes). ``ttl`` bounds how long
    a completed response is replayable.

    ``lock_ttl`` bounds the in-flight marker so a crashed request cannot wedge a
    key forever. **It must exceed the runtime of your slowest handler:** if a
    handler runs longer than ``lock_ttl`` the marker expires mid-flight, and a
    concurrent retry will see no record and re-run the operation.

    ``max_body_bytes`` caps the response size that is cached; larger responses are
    served normally but not stored (so a stream of huge unique-key requests cannot
    grow the store without bound). ``None`` disables the cap.
    """

    header_name: str = DEFAULT_HEADER
    methods: Sequence[str] = ("POST", "PATCH")
    store: str = DEFAULT_STORE
    ttl: int = 86_400
    lock_ttl: int = 60
    max_body_bytes: int | None = 1_048_576

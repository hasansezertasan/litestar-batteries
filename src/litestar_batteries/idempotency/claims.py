"""Optional atomic-claim backends for cross-process idempotency.

Litestar's ``Store`` interface has no atomic check-and-set, so the default
in-flight guard is a per-worker :class:`asyncio.Lock` (best-effort across
processes). Supplying an :class:`AtomicClaim` gives a real cross-process guard:
its :meth:`~AtomicClaim.claim` reserves a key atomically (e.g. Redis ``SET NX``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable


@runtime_checkable
class AtomicClaim(Protocol):
    """A storage backend whose in-flight reservation is atomic.

    When configured, the middleware routes all record I/O through it instead of
    the Litestar store, so concurrent first requests are resolved by the backend
    (not a per-worker lock).
    """

    async def claim(self, key: str, value: bytes, *, ttl: int) -> bytes | None:
        """Atomically reserve ``key`` with ``value`` for ``ttl`` seconds.

        Return ``None`` if the caller won the reservation (key was absent), else
        the bytes already stored under ``key`` (another request holds it).
        """
        ...

    async def set(self, key: str, value: bytes, *, ttl: int) -> None:
        """Overwrite ``key`` with ``value`` for ``ttl`` seconds."""
        ...

    async def delete(self, key: str) -> None:
        """Remove ``key`` (releases the reservation)."""
        ...


class _RedisClient(Protocol):
    """Structural type for the subset of ``redis.asyncio.Redis`` we use."""

    def set(
        self, name: str, value: bytes, *, nx: bool = ..., ex: int | None = ...
    ) -> Awaitable[bool | None]: ...
    def get(self, name: str) -> Awaitable[bytes | None]: ...
    def delete(self, *names: str) -> Awaitable[int]: ...


class RedisAtomicClaim:
    """:class:`AtomicClaim` backed by a ``redis.asyncio.Redis`` client.

    ``redis`` is duck-typed (no hard dependency); any client exposing
    ``set(name, value, nx=, ex=)`` / ``get`` / ``delete`` works::

        from redis.asyncio import Redis
        from litestar_batteries import IdempotencyConfig, IdempotencyPlugin, RedisAtomicClaim

        claim = RedisAtomicClaim(Redis.from_url("redis://localhost:6379"))
        plugin = IdempotencyPlugin(IdempotencyConfig(claim=claim))
    """

    def __init__(self, redis: _RedisClient, *, prefix: str = "idempotency:") -> None:
        self._redis = redis
        self._prefix = prefix

    async def claim(self, key: str, value: bytes, *, ttl: int) -> bytes | None:
        was_set = await self._redis.set(self._prefix + key, value, nx=True, ex=ttl)
        if was_set:
            return None
        # Lost the race (or key already present); return the incumbent record.
        return await self._redis.get(self._prefix + key)

    async def set(self, key: str, value: bytes, *, ttl: int) -> None:
        await self._redis.set(self._prefix + key, value, ex=ttl)

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._prefix + key)

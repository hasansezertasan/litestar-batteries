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

__all__ = ["AtomicClaim", "RedisAtomicClaim"]


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
        # pylint: disable-next=unnecessary-ellipsis
        ...  # pragma: no cover - protocol stub, never called directly.

    async def set(self, key: str, value: bytes, *, expected: bytes, ttl: int) -> bool:
        """Atomically replace ``key`` only if it holds ``expected``; return success."""
        # pylint: disable-next=unnecessary-ellipsis
        ...  # pragma: no cover - protocol stub, never called directly.

    async def delete(self, key: str, *, expected: bytes) -> bool:
        """Atomically remove ``key`` only if it holds ``expected``; return success."""
        # pylint: disable-next=unnecessary-ellipsis
        ...  # pragma: no cover - protocol stub, never called directly.


class _RedisClient(Protocol):
    """Structural type for the subset of ``redis.asyncio.Redis`` we use."""

    def set(
        self, name: str, value: bytes, *, nx: bool = ..., ex: int | None = ...
    ) -> Awaitable[bool | None]: ...  # pragma: no cover - protocol stub.
    def get(self, name: str) -> Awaitable[bytes | None]: ...  # pragma: no cover
    def eval(
        self, script: str, numkeys: int, *args: str | bytes | int
    ) -> Awaitable[int]: ...  # pragma: no cover - protocol stub.


_SET_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[3])
    return 1
end
return 0
"""
_DELETE_IF_OWNER = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


class RedisAtomicClaim:
    """:class:`AtomicClaim` backed by a ``redis.asyncio.Redis`` client.

    ``redis`` is duck-typed (no hard dependency); any client exposing
    ``set(name, value, nx=, ex=)`` / ``get`` / ``eval`` works. Finalization uses
    atomic Lua comparisons against the unique reservation, so an expired owner
    cannot change a newer record::

        from redis.asyncio import Redis
        from litestar_batteries import (
            IdempotencyConfig,
            IdempotencyPlugin,
            RedisAtomicClaim,
        )

        claim = RedisAtomicClaim(Redis.from_url("redis://localhost:6379"))
        plugin = IdempotencyPlugin(IdempotencyConfig(claim=claim))
    """

    def __init__(self, redis: _RedisClient, *, prefix: str = "idempotency:") -> None:
        """Store the Redis client and key prefix.

        Args:
            redis: The ``redis.asyncio``-compatible client to run against.
            prefix: Key prefix namespacing every reservation and record.
        """
        self._redis: _RedisClient = redis
        self._prefix: str = prefix

    async def claim(self, key: str, value: bytes, *, ttl: int) -> bytes | None:
        """Reserve ``key`` via ``SET NX``; return the incumbent on a lost race.

        Args:
            key: The idempotency record key to reserve.
            value: The reservation payload (unique ownership token).
            ttl: Reservation time-to-live in seconds.

        Returns:
            ``None`` when this caller won the reservation, else the bytes
            already stored under ``key``.
        """
        while True:
            was_set = await self._redis.set(self._prefix + key, value, nx=True, ex=ttl)
            if was_set:
                return None
            # Lost the race (or key already present); return the incumbent record.
            incumbent = await self._redis.get(self._prefix + key)
            if incumbent is not None:
                return incumbent
            # The incumbent expired or was released between SET NX and GET; claiming
            # again (rather than returning None) keeps the reservation atomic.

    async def set(self, key: str, value: bytes, *, expected: bytes, ttl: int) -> bool:
        """Persist a completed response only while the reservation is still owned.

        Returns:
            Whether the stored value still held ``expected`` and was replaced.
        """
        return bool(
            await self._redis.eval(
                _SET_IF_OWNER, 1, self._prefix + key, expected, value, ttl
            )
        )

    async def delete(self, key: str, *, expected: bytes) -> bool:
        """Release a reservation only while it is still owned.

        Returns:
            Whether the stored value still held ``expected`` and was removed.
        """
        return bool(
            await self._redis.eval(_DELETE_IF_OWNER, 1, self._prefix + key, expected)
        )

"""Shared idempotency tracking with FIFO eviction.

Used by all Kafka consumer state holders to deduplicate events by ``event_id``.
Maintains a bounded set backed by a deque for deterministic oldest-first eviction.

Usage::

    from _common.idempotency import IdempotencyTracker

    class MyConsumerState:
        def __init__(self):
            self._idempotency = IdempotencyTracker(max_size=10_000)

        def check_idempotency(self, event_id: str) -> bool:
            return self._idempotency.is_duplicate(event_id)
"""

from __future__ import annotations

from collections import deque


class IdempotencyTracker:
    """Bounded idempotency tracker with deterministic FIFO eviction.

    Stores event IDs in a ``set`` for O(1) membership checks and a ``deque``
    for ordered eviction.  When the tracker exceeds ``max_size``, the oldest
    entries are evicted first — guaranteeing recent event IDs are always
    retained.

    Args:
        max_size: Maximum number of event IDs to track before eviction.
    """

    __slots__ = ("max_size", "_seen", "_order")

    def __init__(self, max_size: int = 10_000) -> None:
        self.max_size = max_size
        self._seen: set[str] = set()
        self._order: deque[str] = deque()

    def is_duplicate(self, event_id: str) -> bool:
        """Check if ``event_id`` has been seen before.

        Returns ``True`` if the event is a duplicate and should be skipped.
        Returns ``False`` for empty IDs (never considered duplicates).
        On first sight the ID is recorded for future duplicate detection.
        """
        if not event_id:
            return False
        if event_id in self._seen:
            return True
        self._seen.add(event_id)
        self._order.append(event_id)
        self._evict()
        return False

    def _evict(self) -> None:
        """Remove oldest entries when the tracker exceeds ``max_size``."""
        while len(self._seen) > self.max_size:
            oldest = self._order.popleft()
            self._seen.discard(oldest)

    def __len__(self) -> int:
        return len(self._seen)

    def __contains__(self, event_id: str) -> bool:
        return event_id in self._seen

    def clear(self) -> None:
        """Reset the tracker, removing all recorded event IDs."""
        self._seen.clear()
        self._order.clear()

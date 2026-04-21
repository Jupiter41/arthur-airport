"""Shared consumer health tracking.

Tracks the timestamp of the last successfully processed Kafka message.
Used by ``/health`` and ``/ready`` endpoints to detect stuck consumers
that are technically alive but no longer processing events.

Usage::

    from _common.consumer_health import ConsumerHealthTracker

    health = ConsumerHealthTracker()

    # In consumer loop after processing a message:
    health.mark_message()

    # In /health or /ready endpoint:
    info = health.status()
    # → {"last_message_age_seconds": 3.2, "messages_processed": 42}
"""

from __future__ import annotations

import time


class ConsumerHealthTracker:
    """Tracks consumer message processing timestamps for health checks.

    Thread-safe for single-writer (consumer thread) / multi-reader (HTTP handlers)
    since Python's GIL protects simple attribute assignments.
    """

    __slots__ = ("_last_message_time", "_messages_processed")

    def __init__(self) -> None:
        self._last_message_time: float | None = None
        self._messages_processed: int = 0

    def mark_message(self) -> None:
        """Record that a message was just processed."""
        self._last_message_time = time.monotonic()
        self._messages_processed += 1

    @property
    def last_message_age_seconds(self) -> float | None:
        """Seconds since the last message was processed, or None if no messages yet."""
        if self._last_message_time is None:
            return None
        return time.monotonic() - self._last_message_time

    @property
    def messages_processed(self) -> int:
        return self._messages_processed

    def status(self) -> dict:
        """Return a dict suitable for inclusion in health/ready responses."""
        age = self.last_message_age_seconds
        return {
            "last_message_age_seconds": round(age, 1) if age is not None else None,
            "messages_processed": self._messages_processed,
        }

    def is_healthy(self, max_age_seconds: float = 120.0) -> bool:
        """Check if the consumer is healthy.

        Returns True if:
        - No messages have been received yet (consumer just started)
        - Last message was within ``max_age_seconds``
        """
        age = self.last_message_age_seconds
        if age is None:
            return True  # Just started, no messages expected yet
        return age < max_age_seconds

"""Shared infrastructure wait utilities.

Provides generic retry-with-backoff functions for Neo4j and Kafka connectivity
checks. Eliminates the copy-pasted wait_for_neo4j / wait_for_kafka functions
that existed independently in each service.

Usage:

    from _common.infra import wait_for_kafka_broker

    await wait_for_kafka_broker(brokers="kafka:9092", logger=logger)
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from confluent_kafka import Producer


async def wait_for_kafka_broker(
    brokers: str | None = None,
    logger: Any = None,
    max_attempts: int = 12,
    delay_s: float = 5,
) -> None:
    """Block until Kafka broker is reachable.

    Uses confluent_kafka.Producer.list_topics() as the health probe.
    Retries with linear backoff capped at 6× delay_s.

    Args:
        brokers: Kafka broker address. Defaults to KAFKA_BROKERS env var.
        logger: structlog or stdlib logger instance for progress messages.
        max_attempts: Maximum number of connection attempts.
        delay_s: Base delay between attempts (seconds).

    Raises:
        RuntimeError: If broker is still unreachable after max_attempts.
    """
    brokers = brokers or os.getenv("KAFKA_BROKERS", "kafka:9092")

    for attempt in range(1, max_attempts + 1):
        try:
            p = Producer({"bootstrap.servers": brokers, "socket.timeout.ms": 5000})
            p.list_topics(timeout=5)
            if logger:
                logger.info("kafka connected", attempt=attempt, brokers=brokers)
            return
        except Exception as exc:
            wait = delay_s * min(attempt, 6)
            if logger:
                logger.warning(
                    "kafka not ready",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(exc),
                )
            if attempt < max_attempts:
                await asyncio.sleep(wait)

    raise RuntimeError(f"Kafka not reachable after {max_attempts} attempts at {brokers}")


async def wait_for_neo4j_ready(
    init_fn: Any,
    close_driver_fn: Any = None,
    logger: Any = None,
    max_attempts: int = 12,
    delay_s: float = 5,
) -> None:
    """Block until Neo4j is reachable by repeatedly calling the service's init function.

    Args:
        init_fn: Async callable that initialises the Neo4j driver and verifies connectivity.
                 Should raise on failure.
        close_driver_fn: Optional async callable to close a stale driver between retries.
        logger: structlog or stdlib logger for progress messages.
        max_attempts: Maximum number of connection attempts.
        delay_s: Base delay between attempts (seconds).

    Raises:
        RuntimeError: If Neo4j is still unreachable after max_attempts.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            await init_fn()
            if logger:
                logger.info("neo4j connected", attempt=attempt)
            return
        except Exception as exc:
            wait = delay_s * min(attempt, 6)
            if logger:
                logger.warning(
                    "neo4j not ready",
                    attempt=attempt,
                    max_attempts=max_attempts,
                    error=str(exc),
                )
            if close_driver_fn:
                try:
                    await close_driver_fn()
                except Exception:
                    pass
            if attempt < max_attempts:
                await asyncio.sleep(wait)

    raise RuntimeError(f"Neo4j not reachable after {max_attempts} attempts")

"""Shared async Neo4j driver lifecycle — one holder per process.

Every service used to copy-paste the same ``init_neo4j`` / ``close_neo4j`` /
``get_driver`` block (driver creation, pool tuning from env, connectivity
verify). Only the CONSTRAINTS/INDEXES and the domain queries differ per service.
This module owns the *generic* driver lifecycle; a service keeps its own schema
and query functions and simply delegates driver management here.

Usage (in a service's ``db/neo4j.py``):

    from _common import neo4j_client

    async def init_neo4j() -> None:
        await neo4j_client.init_driver()

    def get_driver():
        return neo4j_client.get_driver()

    async def close_neo4j() -> None:
        await neo4j_client.close_driver()
"""

from __future__ import annotations

import logging
import os

from neo4j import AsyncDriver, AsyncGraphDatabase

logger = logging.getLogger(__name__)

_driver: AsyncDriver | None = None


async def init_driver(
    *,
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    pool_size: int | None = None,
    pool_timeout: float | None = None,
    conn_lifetime: int | None = None,
) -> AsyncDriver:
    """Create the async Neo4j driver and verify connectivity.

    All parameters default to the shared ``NEO4J_*`` environment variables so a
    plain ``await init_driver()`` reproduces the previous per-service behaviour.
    Idempotent-ish: a second call replaces the driver (the caller's retry loop
    closes stale drivers between attempts).
    """
    global _driver
    _driver = AsyncGraphDatabase.driver(
        uri or os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            user or os.getenv("NEO4J_USER", "neo4j"),
            password or os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
        ),
        max_connection_pool_size=pool_size
        if pool_size is not None
        else int(os.getenv("NEO4J_POOL_SIZE", "50")),
        connection_acquisition_timeout=pool_timeout
        if pool_timeout is not None
        else float(os.getenv("NEO4J_POOL_TIMEOUT", "60")),
        max_connection_lifetime=conn_lifetime
        if conn_lifetime is not None
        else int(os.getenv("NEO4J_CONN_LIFETIME", "3600")),
    )
    await _driver.verify_connectivity()
    logger.info("Neo4j driver initialized")
    return _driver


def get_driver() -> AsyncDriver:
    """Return the initialised async Neo4j driver, or raise if not yet initialised."""
    if _driver is None:
        raise RuntimeError("Neo4j driver not initialised")
    return _driver


async def close_driver() -> None:
    """Close the Neo4j driver and release resources."""
    global _driver
    if _driver:
        await _driver.close()
        _driver = None
        logger.info("Neo4j driver closed")


async def check_connectivity() -> bool:
    """Return True if the current driver can verify connectivity."""
    try:
        if _driver is None:
            return False
        await _driver.verify_connectivity()
        return True
    except Exception:
        return False

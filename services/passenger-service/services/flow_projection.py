"""Startup-warmed Neo4j read snapshot for historical passenger status totals."""
import asyncio
import logging
from time import monotonic

from db.neo4j import get_status_counts

logger = logging.getLogger(__name__)
INTERVAL_SECONDS = 15
_counts: dict[str, int] | None = None
_observed_sim_time: str | None = None
_refreshed_at = 0.0
_failed = False
_lock = asyncio.Lock()


async def refresh() -> None:
    global _counts, _observed_sim_time, _refreshed_at, _failed
    from kafka.consumer import get_sim_time

    async with _lock:
        clock = get_sim_time()
        try:
            counts = await get_status_counts()
        except Exception:
            _failed = True
            raise
        # Publish a complete successful query; a failed refresh cannot replace
        # a valid projection with zero or partial counts.
        _counts = dict(counts)
        _observed_sim_time = clock.isoformat() if clock else None
        _refreshed_at = monotonic()
        _failed = False


async def read() -> tuple[dict[str, int], dict]:
    if _counts is None:
        await refresh()
    assert _counts is not None
    age = max(0.0, monotonic() - _refreshed_at)
    return dict(_counts), {
        "counts_observed_sim_time": _observed_sim_time,
        "counts_age_seconds": round(age, 1),
        "counts_stale": _failed or age > 2 * INTERVAL_SECONDS,
    }


async def run(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=INTERVAL_SECONDS)
            return
        except asyncio.TimeoutError:
            pass
        try:
            await refresh()
        except Exception:
            logger.exception("Passenger count refresh failed; retaining last observation")

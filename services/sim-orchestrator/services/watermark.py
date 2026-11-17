"""Tick watermark and clock back-pressure (RC4).

Owners publish ``TickProcessed {owner, sim_time}`` on ``sim.watermark`` after
each committed tick. The clock holds the next tick while the slowest *live*
owner is too far behind, turning silent tick coalescing into visible
back-pressure. An owner silent for ``WATERMARK_STALE_S`` wall seconds is treated
as down: it no longer holds the clock (one crashed service must not freeze the
sim) and is reported as stale instead.

Owners also send ``OwnerHeartbeat`` every few wall seconds from a background
thread and ``OwnerStopped`` on a clean shutdown. An owner that has been
heard beating and then misses ``WATERMARK_HEARTBEAT_STALE_S`` seconds of
beats (a crash) or announced its stop is down at once, instead of after the
full ``WATERMARK_STALE_S``; a slow owner that still beats keeps holding the
clock until its progress itself is ``WATERMARK_STALE_S`` old.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

ENABLED = os.getenv("WATERMARK_BACKPRESSURE", "true").lower() != "false"
MAX_LAG_MIN = float(os.getenv("WATERMARK_MAX_LAG_MIN", "5"))
STALE_S = float(os.getenv("WATERMARK_STALE_S", "30"))
HEARTBEAT_STALE_S = float(os.getenv("WATERMARK_HEARTBEAT_STALE_S", "7"))
TOPIC = "sim.watermark"


class WatermarkTracker:
    def __init__(self, *, max_lag_min: float = MAX_LAG_MIN, stale_s: float = STALE_S,
                 heartbeat_stale_s: float = HEARTBEAT_STALE_S, clock=time.monotonic) -> None:
        self.max_lag_min = max_lag_min
        self.stale_s = stale_s
        self.heartbeat_stale_s = heartbeat_stale_s
        self.clock = clock
        self.marks: dict[str, tuple[datetime, float]] = {}
        self.beats: dict[str, float] = {}

    def beat(self, owner: str) -> None:
        self.beats[owner] = self.clock()

    def stopped(self, owner: str) -> None:
        """A clean shutdown: the owner no longer holds the clock."""
        self.beats[owner] = float("-inf")

    def _down(self, owner: str, now: float, seen: float) -> bool:
        if now - seen > self.stale_s:
            return True
        beat = self.beats.get(owner)
        # Owners that never beat (older builds) fall back to progress staleness.
        return beat is not None and now - beat > self.heartbeat_stale_s

    def observe(self, owner: str, sim_time: datetime) -> None:
        sim_time = sim_time.replace(tzinfo=None)
        current = self.marks.get(owner)
        if current is None or sim_time >= current[0]:
            self.marks[owner] = (sim_time, self.clock())
        else:  # a rewind (reset/restore): accept it, the owner restarted its clock
            self.marks[owner] = (sim_time, self.clock())
        if self.beats.get(owner) is not None:
            self.beat(owner)   # a watermark proves the owner is alive

    def reset(self) -> None:
        self.marks.clear()
        self.beats.clear()

    def live(self) -> dict[str, datetime]:
        now = self.clock()
        return {owner: at for owner, (at, seen) in self.marks.items()
                if not self._down(owner, now, seen)}

    def blocking(self, next_sim_time: datetime, step_minutes: int = 1) -> list[str]:
        """Live owners more than the allowed lag behind ``next_sim_time``."""
        allowed = timedelta(minutes=max(self.max_lag_min, 2 * step_minutes))
        target = next_sim_time.replace(tzinfo=None)
        return sorted(owner for owner, at in self.live().items() if target - at > allowed)

    def status(self, sim_time: datetime) -> dict:
        now = self.clock()
        current = sim_time.replace(tzinfo=None)
        return {
            owner: {
                "sim_time": at.isoformat(),
                "lag_minutes": round((current - at).total_seconds() / 60, 1),
                "stale": self._down(owner, now, seen),
            }
            for owner, (at, seen) in sorted(self.marks.items())
        }


TRACKER = WatermarkTracker()


def handle(envelope: dict, tracker: WatermarkTracker = TRACKER) -> bool:
    event_type = envelope.get("event_type")
    payload = envelope.get("payload") or {}
    if event_type in ("OwnerHeartbeat", "OwnerStopped"):
        owner = payload.get("owner")
        if not owner:
            return False
        if event_type == "OwnerStopped":
            tracker.stopped(owner)
        else:
            tracker.beat(owner)
        return True
    if event_type != "TickProcessed":
        return False
    owner, at = payload.get("owner"), payload.get("sim_time")
    if not owner or not at:
        return False
    try:
        tracker.observe(owner, datetime.fromisoformat(str(at).replace("Z", "")))
    except ValueError:
        return False
    return True


async def run_consumer(stop: asyncio.Event) -> None:
    """Follow ``sim.watermark`` from the live end (per-instance group, no commits)."""
    from confluent_kafka import Consumer
    consumer = Consumer({
        "bootstrap.servers": os.getenv("KAFKA_BROKERS", "kafka:9092"),
        "group.id": f"sim-watermark-{uuid.uuid4().hex[:8]}",
        "auto.offset.reset": "latest",
        "enable.auto.commit": False,
    })
    consumer.subscribe([TOPIC])
    loop = asyncio.get_running_loop()
    try:
        while not stop.is_set():
            msgs = await loop.run_in_executor(None, lambda: consumer.consume(200, timeout=0.5))
            for msg in msgs or []:
                if msg.error():
                    continue
                try:
                    handle(json.loads(msg.value()))
                except Exception:
                    logger.debug("Bad watermark message", exc_info=True)
    finally:
        consumer.close()

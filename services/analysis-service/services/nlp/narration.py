"""Simulation narration engine (P5-2-3).

Generates real-time running commentary of significant airport events.
Accumulates events and periodically generates narrative text via LLM
or structured templates.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from services.nlp.llm import is_llm_available, llm_chat

if TYPE_CHECKING:
    from services.state import OperationalState

logger = logging.getLogger(__name__)

# ── Configuration ────────────────────────────────────────────

MAX_EVENT_BUFFER = 100
NARRATION_INTERVAL_TICKS = 5  # Generate narration every 5 sim-minutes
MAX_NARRATION_HISTORY = 50

SYSTEM_PROMPT = """You are a professional aviation commentator narrating operations at Arthur International Airport (KART).

Generate a concise 2-3 sentence narration of the significant events that just occurred.
Write in present tense, as if broadcasting live. Reference specific times, flight IDs (first 8 chars),
terminals, and locations. Mention any concerning trends (rising delays, queue build-up, incidents).

Style: professional, clear, British English aviation style. Under 100 words."""


# ── Data structures ──────────────────────────────────────────


@dataclass
class NarrationEvent:
    """A significant event to be narrated."""
    event_type: str
    timestamp: datetime
    summary: str
    significance: int = 1  # 1=routine, 2=notable, 3=critical


# ── Narration Engine ─────────────────────────────────────────


class NarrationEngine:
    """Accumulates significant events and generates periodic narratives."""

    def __init__(self) -> None:
        self._enabled: bool = False
        self._event_buffer: deque[NarrationEvent] = deque(maxlen=MAX_EVENT_BUFFER)
        self._narration_history: deque[dict] = deque(maxlen=MAX_NARRATION_HISTORY)
        self._ticks_since_narration: int = 0
        self._interval: int = NARRATION_INTERVAL_TICKS

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value
        logger.info("Narration mode %s", "enabled" if value else "disabled")

    def record_event(
        self,
        event_type: str,
        timestamp: datetime,
        summary: str,
        significance: int = 1,
    ) -> None:
        """Record a significant event for narration."""
        if not self._enabled:
            return
        self._event_buffer.append(NarrationEvent(
            event_type=event_type,
            timestamp=timestamp,
            summary=summary,
            significance=significance,
        ))

    async def on_tick(
        self, state: "OperationalState",
    ) -> dict[str, Any] | None:
        """Called each sim-minute. Returns narration dict if it's time to narrate."""
        if not self._enabled:
            return None

        self._ticks_since_narration += 1
        if self._ticks_since_narration < self._interval:
            return None

        self._ticks_since_narration = 0

        # Collect events since last narration
        events = list(self._event_buffer)
        self._event_buffer.clear()

        if not events:
            return None

        # Sort by significance (most significant first)
        events.sort(key=lambda e: e.significance, reverse=True)

        # Generate narration
        narration_text = await self._generate(events, state)
        if not narration_text:
            return None

        entry = {
            "text": narration_text,
            "sim_time": state.sim_time.isoformat() if state.sim_time else None,
            "event_count": len(events),
            "source": "llm" if is_llm_available() else "template",
        }
        self._narration_history.append(entry)
        return entry

    async def _generate(
        self,
        events: list[NarrationEvent],
        state: "OperationalState",
    ) -> str | None:
        """Generate narration text from accumulated events."""
        # Build event summary
        event_text = "\n".join(
            f"- [{e.timestamp.strftime('%H:%M') if e.timestamp else '??:??'}] "
            f"{e.summary} (significance: {e.significance})"
            for e in events[:20]  # limit to top 20
        )

        if is_llm_available():
            user_message = (
                f"Time: {state.sim_time.isoformat() if state.sim_time else 'unknown'}\n"
                f"Weather: {state.weather.category}\n"
                f"Active incidents: {len(state.active_incidents)}\n\n"
                f"Recent events:\n{event_text}"
            )
            result = await llm_chat(SYSTEM_PROMPT, user_message)
            if result:
                return result

        # Template fallback
        return self._template_narrate(events, state)

    def _template_narrate(
        self,
        events: list[NarrationEvent],
        state: "OperationalState",
    ) -> str:
        """Generate template-based narration."""
        time_str = state.sim_time.strftime("%H:%M") if state.sim_time else "??"
        parts = [f"At {time_str} local time at Arthur International:"]

        # Group by significance
        critical = [e for e in events if e.significance >= 3]
        notable = [e for e in events if e.significance == 2]
        routine = [e for e in events if e.significance <= 1]

        if critical:
            parts.append(critical[0].summary + ".")
        elif notable:
            parts.append(notable[0].summary + ".")
        elif routine:
            parts.append(f"{len(routine)} routine operations recorded.")

        # Add status line
        active = [
            f for f in state.flights.values()
            if f.status not in ("completed", "cancelled")
        ]
        delayed = [f for f in active if f.delay_minutes > 0]
        if delayed:
            total_delay = sum(f.delay_minutes for f in delayed)
            parts.append(
                f"{len(delayed)} flights are experiencing delays "
                f"totaling {total_delay:.0f} minutes."
            )
        else:
            parts.append("All flights are operating on schedule.")

        if state.active_incidents:
            parts.append(
                f"{len(state.active_incidents)} active incident(s) being managed."
            )

        return " ".join(parts)

    def get_history(self, limit: int = 20) -> list[dict]:
        """Return recent narration entries."""
        return list(reversed(list(self._narration_history)))[:limit]

    def get_settings(self) -> dict:
        return {
            "enabled": self._enabled,
            "interval_minutes": self._interval,
            "history_count": len(self._narration_history),
            "buffer_count": len(self._event_buffer),
        }


# ── Module singleton ─────────────────────────────────────────

narration = NarrationEngine()

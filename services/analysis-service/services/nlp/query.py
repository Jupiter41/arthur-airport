"""Natural language query engine for airport operations (P5-2-1).

Accepts plain English questions about the current simulation state
and returns structured answers. Uses LLM when available, falls back
to template-based pattern matching.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from services.nlp.llm import is_llm_available, llm_chat

if TYPE_CHECKING:
    from services.state import OperationalState

logger = logging.getLogger(__name__)

# ── System prompt for LLM mode ──────────────────────────────

SYSTEM_PROMPT = """You are an airport operations analyst for Arthur International Airport (KART).
You have access to the current real-time state of the simulation. Answer questions
concisely and precisely based on the data provided. Use specific numbers.

When asked about delays, include the number of delayed flights and total delay minutes.
When asked about passengers, reference security queue depths and wait times.
When asked hypothetical "what if" questions, explain the likely cascading effects.

Keep answers under 200 words. Be professional and direct."""


async def query(
    question: str,
    state: "OperationalState",
    bottlenecks: list[dict] | None = None,
    recommendations: list[dict] | None = None,
) -> dict[str, Any]:
    """Answer a natural language question about the simulation state.

    Returns a dict with 'answer', 'source' (llm|template), and 'context'.
    """
    context = _build_context(state, bottlenecks, recommendations)

    if is_llm_available():
        answer = await _llm_query(question, context)
        if answer:
            return {"answer": answer, "source": "llm", "context_summary": context[:500]}

    # Template fallback
    answer = _template_query(question, state, bottlenecks, recommendations)
    return {"answer": answer, "source": "template", "context_summary": context[:500]}


# ── LLM mode ────────────────────────────────────────────────


async def _llm_query(question: str, context: str) -> str | None:
    """Send question + context to LLM."""
    user_message = f"""Current airport state:
{context}

Question: {question}"""

    return await llm_chat(SYSTEM_PROMPT, user_message, temperature=0.3)


# ── Context builder ─────────────────────────────────────────


def _build_context(
    state: "OperationalState",
    bottlenecks: list[dict] | None = None,
    recommendations: list[dict] | None = None,
) -> str:
    """Build a structured text context from operational state."""
    parts = []

    # Sim time
    if state.sim_time:
        parts.append(f"Simulation time: {state.sim_time.isoformat()}")

    # Flight summary
    flights = list(state.flights.values())
    active = [f for f in flights if f.status not in ("completed", "cancelled")]
    delayed = [f for f in active if f.delay_minutes > 0]
    status_counts: dict[str, int] = {}
    for f in active:
        status_counts[f.status] = status_counts.get(f.status, 0) + 1

    parts.append(f"\nFlights: {len(active)} active ({', '.join(f'{v} {k}' for k, v in sorted(status_counts.items()))})")
    if delayed:
        total_delay = sum(f.delay_minutes for f in delayed)
        parts.append(f"Delayed flights: {len(delayed)} (total {total_delay:.0f} delay minutes)")
        top_delayed = sorted(delayed, key=lambda f: f.delay_minutes, reverse=True)[:5]
        for f in top_delayed:
            parts.append(f"  - {f.flight_id[:8]}… ({f.flight_type}): {f.delay_minutes:.0f}min delay, status={f.status}")

    # Security
    parts.append("\nSecurity queues:")
    for t, sec in state.security.items():
        parts.append(
            f"  {t}: queue={sec.queue_depth}, "
            f"wait={sec.forecast_wait_minutes:.0f}min, "
            f"lanes={sec.open_lanes}"
        )

    # Weather
    w = state.weather
    parts.append(f"\nWeather: {w.category} (visibility={w.visibility_m}m, wind={w.wind_speed_kt}kt, runway capacity={w.runway_capacity_pct:.0f}%)")

    # Incidents
    if state.active_incidents:
        parts.append(f"\nActive incidents ({len(state.active_incidents)}):")
        for iid, inc in state.active_incidents.items():
            parts.append(f"  - {inc.get('type', '?')} severity={inc.get('severity', '?')} at {inc.get('location', '?')}")

    # Bottlenecks
    if bottlenecks:
        parts.append(f"\nActive bottlenecks ({len(bottlenecks)}):")
        for bn in bottlenecks:
            parts.append(f"  - {bn.get('type', '?')} ({bn.get('severity', '?')}) in {bn.get('zone', '?')}: {bn.get('root_cause', '?')}")

    # Recommendations
    if recommendations:
        parts.append(f"\nTop recommendations ({len(recommendations)}):")
        for rec in recommendations[:3]:
            parts.append(f"  - {rec.get('action_type', '?')}: {rec.get('description', '?')} (confidence={rec.get('confidence_score', 0):.2f})")

    # Vehicle utilisation
    if state.vehicles:
        parts.append("\nGround vehicles:")
        for vtype, v in state.vehicles.items():
            parts.append(f"  {vtype}: {v.dispatched}/{v.total} dispatched ({v.utilisation_pct:.0f}%)")

    return "\n".join(parts)


# ── Template fallback ────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"delay|late|behind", re.I), "delays"),
    (re.compile(r"connect|miss|transfer", re.I), "connections"),
    (re.compile(r"security|queue|wait|line", re.I), "security"),
    (re.compile(r"weather|wind|visibility|fog|rain", re.I), "weather"),
    (re.compile(r"incident|alert|emergency", re.I), "incidents"),
    (re.compile(r"bottleneck|constraint|capacity", re.I), "bottlenecks"),
    (re.compile(r"recommend|suggest|action|intervention", re.I), "recommendations"),
    (re.compile(r"gate|terminal|parking", re.I), "gates"),
    (re.compile(r"baggage|bag|luggage|carousel", re.I), "baggage"),
    (re.compile(r"vehicle|truck|tug|pushback", re.I), "vehicles"),
    (re.compile(r"runway|landing|takeoff|capacity", re.I), "runway"),
    (re.compile(r"how many|count|total|number", re.I), "summary"),
]


def _template_query(
    question: str,
    state: "OperationalState",
    bottlenecks: list[dict] | None = None,
    recommendations: list[dict] | None = None,
) -> str:
    """Pattern-match the question and generate a template-based response."""
    # Determine intent
    intent = "summary"
    for pattern, intent_name in _PATTERNS:
        if pattern.search(question):
            intent = intent_name
            break

    active_flights = [
        f for f in state.flights.values()
        if f.status not in ("completed", "cancelled")
    ]
    delayed = [f for f in active_flights if f.delay_minutes > 0]

    if intent == "delays":
        if not delayed:
            return "No flights are currently delayed."
        total_delay = sum(f.delay_minutes for f in delayed)
        top = sorted(delayed, key=lambda f: f.delay_minutes, reverse=True)[:3]
        lines = [f"{len(delayed)} flights are delayed with a total of {total_delay:.0f} delay minutes."]
        lines.append("Top delayed flights:")
        for f in top:
            lines.append(f"- {f.flight_id[:8]}… ({f.flight_type}): {f.delay_minutes:.0f}min")
        return "\n".join(lines)

    elif intent == "security":
        lines = ["Security queue status:"]
        for t, sec in state.security.items():
            lines.append(
                f"- {t}: {sec.queue_depth} pax queued, "
                f"~{sec.forecast_wait_minutes:.0f}min wait, "
                f"{sec.open_lanes} lanes open"
            )
        return "\n".join(lines)

    elif intent == "weather":
        w = state.weather
        return (
            f"Current weather: {w.category}\n"
            f"Visibility: {w.visibility_m:.0f}m, Wind: {w.wind_speed_kt:.0f}kt\n"
            f"Runway capacity: {w.runway_capacity_pct:.0f}%"
        )

    elif intent == "incidents":
        if not state.active_incidents:
            return "No active incidents."
        lines = [f"{len(state.active_incidents)} active incident(s):"]
        for inc in state.active_incidents.values():
            lines.append(
                f"- {inc.get('type', '?')} (severity: {inc.get('severity', '?')}) "
                f"at {inc.get('location', '?')}"
            )
        return "\n".join(lines)

    elif intent == "bottlenecks":
        if not bottlenecks:
            return "No active bottlenecks detected."
        lines = [f"{len(bottlenecks)} active bottleneck(s):"]
        for bn in bottlenecks:
            lines.append(
                f"- {bn.get('type', '?')} ({bn.get('severity', '?')}) "
                f"in {bn.get('zone', '?')}: {bn.get('root_cause', '?')}"
            )
        return "\n".join(lines)

    elif intent == "recommendations":
        if not recommendations:
            return "No active recommendations."
        lines = [f"{len(recommendations)} active recommendation(s):"]
        for rec in recommendations[:3]:
            lines.append(
                f"- {rec.get('action_type', '?')}: {rec.get('description', '?')} "
                f"(confidence: {rec.get('confidence_score', 0):.0%})"
            )
        return "\n".join(lines)

    elif intent == "gates":
        free = state.get_free_gates_by_terminal()
        lines = ["Gate availability:"]
        for t, free_count in free.items():
            lines.append(f"- {t}: {free_count} free gates")
        return "\n".join(lines)

    elif intent == "vehicles":
        if not state.vehicles:
            return "No ground vehicle data available."
        lines = ["Ground vehicle status:"]
        for vtype, v in state.vehicles.items():
            lines.append(
                f"- {vtype}: {v.dispatched}/{v.total} dispatched "
                f"({v.utilisation_pct:.0f}% utilisation)"
            )
        return "\n".join(lines)

    elif intent == "baggage":
        if not state.baggage_zones:
            return "No baggage zone data available."
        lines = ["Baggage zone utilisation:"]
        for zone_name, zone in sorted(state.baggage_zones.items()):
            lines.append(
                f"- {zone_name}: {zone.current_count}/{zone.capacity} "
                f"({zone.utilisation_pct:.0f}%)"
            )
        return "\n".join(lines)

    # Default summary
    lines = [
        f"Airport status at {state.sim_time.isoformat() if state.sim_time else 'unknown'}:",
        f"- {len(active_flights)} active flights ({len(delayed)} delayed)",
        f"- Weather: {state.weather.category}",
        f"- Active incidents: {len(state.active_incidents)}",
    ]
    free = state.get_free_gates_by_terminal()
    for t, cnt in free.items():
        lines.append(f"- {t}: {cnt} free gates")
    return "\n".join(lines)

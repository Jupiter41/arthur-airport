"""After-action report generator (P5-2-4).

Generates a 2-page natural language summary of a simulation run or
scenario execution, including what happened, interventions applied,
and lessons learned.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from services.nlp.llm import is_llm_available, llm_chat

if TYPE_CHECKING:
    from services.state import OperationalState

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an aviation operations analyst writing an after-action report for Arthur International Airport (KART).

Write a structured post-operations summary covering:
1. **Operational Overview** — time period, weather, flight volume
2. **Key Events** — delays, incidents, bottlenecks, and their resolution
3. **Interventions Applied** — what recommendations were applied, their outcomes
4. **Performance Metrics** — total delay, missed connections, queue peaks
5. **Lessons Learned** — what could be improved for next time

Format as Markdown. Keep to ~500 words. Be specific with numbers and times."""


async def generate_report(
    state: "OperationalState",
    bottleneck_history: list[dict] | None = None,
    recommendation_history: list[dict] | None = None,
    autonomous_log: list[dict] | None = None,
    whatif_log: list[dict] | None = None,
    scenario_name: str | None = None,
) -> dict[str, Any]:
    """Generate an after-action report.

    Returns dict with 'report' (markdown text), 'source', and metadata.
    """
    context = _build_report_context(
        state, bottleneck_history, recommendation_history,
        autonomous_log, whatif_log, scenario_name,
    )

    if is_llm_available():
        report = await _llm_report(context)
        if report:
            return {
                "report": report,
                "source": "llm",
                "generated_at": datetime.utcnow().isoformat(),
                "scenario": scenario_name,
            }

    # Template fallback
    report = _template_report(
        state, bottleneck_history, recommendation_history,
        autonomous_log, scenario_name,
    )
    return {
        "report": report,
        "source": "template",
        "generated_at": datetime.utcnow().isoformat(),
        "scenario": scenario_name,
    }


async def _llm_report(context: str) -> str | None:
    """Generate report via LLM."""
    return await llm_chat(SYSTEM_PROMPT, context, temperature=0.5, max_tokens=2048)


def _build_report_context(
    state: "OperationalState",
    bottleneck_history: list[dict] | None,
    recommendation_history: list[dict] | None,
    autonomous_log: list[dict] | None,
    whatif_log: list[dict] | None,
    scenario_name: str | None,
) -> str:
    """Build context string for LLM report generation."""
    parts = []

    if scenario_name:
        parts.append(f"Scenario: {scenario_name}")

    parts.append(f"Current sim time: {state.sim_time.isoformat() if state.sim_time else 'unknown'}")
    parts.append(f"Weather: {state.weather.category}")

    # Flight metrics
    flights = list(state.flights.values())
    active = [f for f in flights if f.status not in ("completed", "cancelled")]
    delayed = [f for f in active if f.delay_minutes > 0]
    total_delay = sum(f.delay_minutes for f in delayed)

    parts.append(f"\nFlights: {len(flights)} total, {len(active)} active, {len(delayed)} delayed")
    parts.append(f"Total delay: {total_delay:.0f} minutes")

    # Security
    parts.append("\nSecurity queues:")
    for t, sec in state.security.items():
        parts.append(f"  {t}: queue={sec.queue_depth}, wait={sec.forecast_wait_minutes:.0f}min")

    # Bottleneck history
    if bottleneck_history:
        parts.append(f"\nBottleneck history ({len(bottleneck_history)} events):")
        for bn in bottleneck_history[-10:]:
            parts.append(f"  - {bn.get('type', '?')} in {bn.get('zone', '?')}: {bn.get('root_cause', '?')}")

    # Recommendations
    if recommendation_history:
        parts.append(f"\nRecommendations issued: {len(recommendation_history)}")
        for rec in recommendation_history[-5:]:
            parts.append(
                f"  - {rec.get('action_type', '?')}: {rec.get('description', '?')} "
                f"(applied: {rec.get('applied', False)})"
            )

    # Autonomous actions
    if autonomous_log:
        parts.append(f"\nAutonomous actions taken: {len(autonomous_log)}")
        for action in autonomous_log[-5:]:
            parts.append(
                f"  - {action.get('action_type', '?')} at {action.get('applied_at', '?')}"
            )

    # What-if queries
    if whatif_log:
        parts.append(f"\nWhat-if queries: {len(whatif_log)}")

    return "\n".join(parts)


def _template_report(
    state: "OperationalState",
    bottleneck_history: list[dict] | None,
    recommendation_history: list[dict] | None,
    autonomous_log: list[dict] | None,
    scenario_name: str | None,
) -> str:
    """Generate a structured template-based report in Markdown."""
    flights = list(state.flights.values())
    active = [f for f in flights if f.status not in ("completed", "cancelled")]
    delayed = [f for f in active if f.delay_minutes > 0]
    total_delay = sum(f.delay_minutes for f in delayed)

    sim_time = state.sim_time.isoformat() if state.sim_time else "unknown"

    lines = [
        "# After-Action Report — Arthur International Airport (KART)",
        "",
        f"**Report generated:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        f"**Simulation time:** {sim_time}",
    ]

    if scenario_name:
        lines.append(f"**Scenario:** {scenario_name}")

    lines.extend([
        "",
        "## 1. Operational Overview",
        "",
        f"- **Total flights:** {len(flights)}",
        f"- **Active flights:** {len(active)}",
        f"- **Delayed flights:** {len(delayed)}",
        f"- **Total delay:** {total_delay:.0f} minutes",
        f"- **Weather:** {state.weather.category} "
        f"(visibility {state.weather.visibility_m:.0f}m, "
        f"wind {state.weather.wind_speed_kt:.0f}kt)",
        f"- **Active incidents:** {len(state.active_incidents)}",
        "",
        "## 2. Security Queue Performance",
        "",
    ])

    for t, sec in state.security.items():
        lines.append(f"- **{t}:** {sec.queue_depth} in queue, ~{sec.forecast_wait_minutes:.0f}min wait, {sec.open_lanes} lanes")

    # Bottlenecks
    lines.extend(["", "## 3. Bottlenecks Detected", ""])
    if bottleneck_history:
        lines.append(f"{len(bottleneck_history)} bottleneck(s) detected during this period:")
        lines.append("")
        lines.append("| Type | Severity | Zone | Root Cause |")
        lines.append("|------|----------|------|------------|")
        for bn in bottleneck_history[-10:]:
            lines.append(
                f"| {bn.get('type', '-')} | {bn.get('severity', '-')} "
                f"| {bn.get('zone', '-')} | {bn.get('root_cause', '-')} |"
            )
    else:
        lines.append("No bottlenecks detected.")

    # Interventions
    lines.extend(["", "## 4. Interventions", ""])
    total_interventions = (
        len(recommendation_history or []) + len(autonomous_log or [])
    )
    if total_interventions > 0:
        lines.append(f"{total_interventions} intervention(s) applied:")
        if autonomous_log:
            lines.append(f"- **Autonomous actions:** {len(autonomous_log)}")
            for a in autonomous_log[-5:]:
                lines.append(f"  - {a.get('action_type', '?')} at {a.get('applied_at', '?')}")
    else:
        lines.append("No interventions were applied.")

    # Summary
    lines.extend([
        "",
        "## 5. Summary",
        "",
        f"During this simulation period, {len(active)} flights were managed "
        f"with {total_delay:.0f} total delay minutes across {len(delayed)} delayed flights. "
        f"{'No bottlenecks were detected.' if not bottleneck_history else f'{len(bottleneck_history)} bottleneck(s) were identified and managed.'}",
    ])

    return "\n".join(lines)

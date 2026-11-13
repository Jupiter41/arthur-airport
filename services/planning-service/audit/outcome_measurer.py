"""Automatic outcome measurement for applied recommendations (roadmap G8, A58).

``RECOMMENDATION_MEASUREMENT_DELAY_MIN`` simulation minutes after a logged
recommendation is applied, the measurer compares the airport cost charged to
its target (Flight / Terminal / Incident) in the window before application
with the same-length window after it, and subtracts the change observed for
untreated units of the same kind over the same windows. That
difference-in-differences is the attributed saving; the untreated change is
the counterfactual. With no untreated comparable unit the result is a labelled
pre/post observation that is not eligible for calibration.

Simulation time comes from the persisted ``SimState`` node, never the wall
clock. Measurement is idempotent: the conditional repository update attaches
an outcome once and commits a ``RecommendationOutcomeMeasured`` fact with it.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import structlog

from db.store import get_repository

logger = structlog.get_logger(__name__)

TARGET_RELATIONSHIPS = {"Flight": "FOR_FLIGHT", "Terminal": "FOR_TERMINAL", "Incident": "CAUSED_BY"}
ATTRIBUTION_VERSION = "planning-attribution-v1"


def delay_minutes() -> int:
    return max(1, int(os.getenv("RECOMMENDATION_MEASUREMENT_DELAY_MIN", "30")))


def _utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def due(entries: list[dict], now: datetime, delay: int | None = None) -> list[dict]:
    """Applied, unmeasured entries with a measurable target whose window has elapsed."""
    window = timedelta(minutes=delay if delay is not None else delay_minutes())
    result = []
    for entry in entries:
        applied = _utc(entry.get("applied_at"))
        if (entry.get("was_applied") and entry.get("actual_saving_eur") is None
                and entry.get("target_type") in TARGET_RELATIONSHIPS and entry.get("target_id")
                and applied is not None and _utc(now) >= applied + window):
            result.append(entry)
    return result


def attribute(target_id: str, costs: dict[str, dict[str, float]], window_minutes: int) -> dict:
    """Pure difference-in-differences of airport cost around application.

    ``costs`` maps unit id → ``{"pre": eur, "post": eur}`` for the target and
    every untreated unit of the same kind charged in either window.
    """
    treated = costs.get(target_id, {"pre": 0.0, "post": 0.0})
    treated_change = treated["post"] - treated["pre"]
    controls = [v["post"] - v["pre"] for k, v in costs.items() if k != target_id]
    base = {"version": ATTRIBUTION_VERSION, "metric": "airport_cost_eur", "window_minutes": window_minutes,
            "treated_pre_eur": round(treated["pre"], 2), "treated_post_eur": round(treated["post"], 2),
            "treated_change_eur": round(treated_change, 2), "control_count": len(controls),
            "causal_claim": False}
    if not controls:
        return {**base, "method": "pre_post", "calibration_eligible": False,
                "reason": "no untreated comparable unit charged in the same windows",
                "counterfactual_post_eur": round(treated["pre"], 2),
                "actual_saving_eur": round(-treated_change, 2)}
    control_change = sum(controls) / len(controls)
    return {**base, "method": "difference_in_differences", "calibration_eligible": True,
            "control_change_eur": round(control_change, 2),
            "counterfactual_post_eur": round(treated["pre"] + control_change, 2),
            "actual_saving_eur": round(-(treated_change - control_change), 2)}


def current_sim_state() -> tuple[datetime, int] | None:
    with get_repository().driver.session() as session:
        row = session.run("MATCH (s:SimState {id: 'airport'}) RETURN s.sim_time AS at, s.day_number AS day").single()
    if not row or _utc(row["at"]) is None:
        return None
    return _utc(row["at"]), int(row["day"] or 1)


def _days(now: datetime, day_now: int, start: datetime, end: datetime) -> list[int]:
    first = day_now - (now.date() - start.date()).days - 1
    last = day_now - (now.date() - end.date()).days + 1
    return list(range(max(1, first), max(1, last) + 1))


def window_costs(target_type: str, applied: datetime, window: int, now: datetime, day_now: int) -> dict:
    """Airport cost per unit of ``target_type`` in the pre/post windows."""
    relationship = TARGET_RELATIONSHIPS[target_type]
    start, end = applied - timedelta(minutes=window), applied + timedelta(minutes=window)
    query = (f"MATCH (c:CostRecord)-[:{relationship}]->(t:{target_type}) "
             "WHERE c.sim_day IN $days AND coalesce(c.is_revenue, false) = false "
             "RETURN t.id AS id, c.sim_time AS at, c.amount_eur AS eur")
    costs: dict[str, dict[str, float]] = {}
    with get_repository().driver.session() as session:
        for row in session.run(query, days=_days(now, day_now, start, end)):
            at = _utc(row["at"])
            if at is None or not start <= at < end or row["eur"] is None:
                continue
            bucket = costs.setdefault(row["id"], {"pre": 0.0, "post": 0.0})
            bucket["pre" if at < applied else "post"] += float(row["eur"])
    return costs


def measure_due() -> int:
    """One measurement pass; returns how many outcomes were attached."""
    from audit.audit_trail import record_measured_outcome

    state = current_sim_state()
    if state is None:
        return 0
    now, day_now = state
    window = delay_minutes()
    measured = 0
    for entry in due(get_repository().list("RecommendationLog"), now, window):
        applied = _utc(entry["applied_at"])
        costs = window_costs(entry["target_type"], applied, window, now, day_now)
        costs.setdefault(entry["target_id"], {"pre": 0.0, "post": 0.0})
        attribution = attribute(entry["target_id"], costs, window)
        if record_measured_outcome(entry["id"], attribution, now.isoformat()) is not None:
            measured += 1
            logger.info("recommendation outcome measured", recommendation_id=entry["id"],
                        method=attribution["method"], actual_saving_eur=attribution["actual_saving_eur"])
    return measured


async def run(stop: asyncio.Event, interval: float = 5.0) -> None:
    while not stop.is_set():
        try:
            await asyncio.to_thread(measure_due)
        except Exception:
            logger.exception("recommendation outcome measurement failed; retrying")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass

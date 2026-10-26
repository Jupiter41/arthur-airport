"""Automatic outcome measurement for executed proposals (roadmap G8).

The analysis engine recorded *predicted* impact (confidence, ranking) but never
the *actual* result of an executed action — so predicted-vs-actual could not be
compared and `record_outcome` was never called. This module supplies the two
**pure** pieces the sim-clock-driven scheduler needs:

- :func:`due_for_outcome` — which executed proposals are ready to measure
  (executed, not yet measured, and ``OUTCOME_DELAY_MIN`` sim-minutes elapsed).
- :func:`measure_outcome` — what actually happened, read from the current
  operational ``state``.

**This measures the observed condition after the action, not a counterfactual.**
It does not claim the action *caused* the change (no baseline/no-action arm) —
that attribution, and prediction calibration, are deferred (see §10 G8). Outcomes
are honestly flagged ``measurable: false`` for actions we cannot yet evaluate,
rather than fabricating a number.

Pure: no I/O, no global state.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# How long after execution to let effects settle before measuring.
OUTCOME_DELAY_MIN = 30


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def due_for_outcome(documents: list[dict], now: datetime) -> list[dict]:
    """Executed proposals whose outcome is unmeasured and now due.

    A proposal is due when it is ``executed``, has no ``actual_outcome`` yet, and
    at least :data:`OUTCOME_DELAY_MIN` sim-minutes have passed since ``executed_at``.
    """
    due: list[dict] = []
    # Parsed executed_at is naive (tz stripped); match that for a safe compare,
    # since state.sim_time may be timezone-aware.
    if now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    cutoff = now - timedelta(minutes=OUTCOME_DELAY_MIN)
    for doc in documents:
        if doc.get("status") != "executed" or doc.get("actual_outcome") is not None:
            continue
        executed_at = _parse(doc.get("executed_at"))
        if executed_at is not None and executed_at <= cutoff:
            due.append(doc)
    return due


def measure_outcome(action_type: str, parameters: dict, state) -> dict:
    """Measure the observed condition targeted by an executed action.

    Returns a dict always carrying ``measured_sim_minutes`` and ``measurable``;
    measurable outcomes add action-specific observations. Never raises on missing
    state — an absent entity is itself an observation.
    """
    parameters = parameters or {}
    base = {"measured_sim_minutes": OUTCOME_DELAY_MIN, "measurable": True}

    if action_type in ("resolve_incident", "contain_incident"):
        incident_id = parameters.get("incident_id")
        incident = (getattr(state, "active_incidents", {}) or {}).get(incident_id)
        status = incident.get("status") if isinstance(incident, dict) else None
        if action_type == "resolve_incident":
            resolved = incident is None or status == "resolved"
        else:  # contain_incident
            resolved = incident is None or status in ("contained", "resolved")
        return {**base, "target": "incident", "incident_id": incident_id,
                "incident_status": status, "bottleneck_resolved": resolved}

    if action_type == "reassign_gate":
        flight_id = parameters.get("flight_id")
        flight = (getattr(state, "flights", {}) or {}).get(flight_id)
        gate = getattr(flight, "gate", None) if flight is not None else None
        return {**base, "target": "flight_gate", "flight_id": flight_id,
                "gate": gate, "bottleneck_resolved": gate is not None}

    if action_type == "open_security_lane":
        terminal = parameters.get("terminal")
        sec = (getattr(state, "security", {}) or {}).get(terminal)
        wait = getattr(sec, "forecast_wait_minutes", None) if sec is not None else None
        lanes = getattr(sec, "open_lanes", None) if sec is not None else None
        return {**base, "target": "security", "terminal": terminal,
                "current_wait_minutes": wait, "open_lanes": lanes}

    # No measurement model yet for this action type — say so honestly.
    return {"measured_sim_minutes": OUTCOME_DELAY_MIN, "measurable": False,
            "reason": f"no outcome model for action_type {action_type!r}"}

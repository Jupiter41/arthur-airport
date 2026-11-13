"""Automatic outcome measurement for executed proposals (roadmap G8).

The analysis engine recorded *predicted* impact (confidence, ranking) but never
the *actual* result of an executed action — so predicted-vs-actual could not be
compared and `record_outcome` was never called. This module supplies the two
**pure** pieces the sim-clock-driven scheduler needs:

- :func:`due_for_outcome` — which executed proposals are ready to measure
  (executed, not yet measured, and ``OUTCOME_DELAY_MIN`` sim-minutes elapsed).
- :func:`measure_outcome` — what actually happened, read from the current
  operational ``state``.

Attribution (A58): :func:`observe_baseline` records the targeted condition and
untreated comparable units (other checkpoints, other gate-less flights, other
active incidents) when the command is first dispatched. :func:`attribute`
compares the treated change with the untreated change over the same window
(difference-in-differences / control-rate lift). The untreated arm is the
counterfactual estimate. Without fresh comparable controls the result is a
pre/post observation flagged ``calibration_eligible: false``; it is never used
to calibrate predictions. Outcomes remain ``measurable: false`` for actions with
no measurement model, rather than fabricating a number.

Pure: no I/O, no global state.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

# How long after execution to let effects settle before measuring.
OUTCOME_DELAY_MIN = 30


def _parse(ts: object) -> datetime | None:
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return _utc(datetime.fromisoformat(ts))
    except (ValueError, TypeError):
        return None


def _utc(value: datetime) -> datetime:
    return (value.astimezone(timezone.utc) if value.tzinfo is not None
            else value.replace(tzinfo=timezone.utc))


def elapsed_minutes(executed_at: str, now: datetime) -> float:
    executed = _parse(executed_at)
    if executed is None:
        raise ValueError("Invalid executed_at timestamp")
    return (_utc(now) - executed).total_seconds() / 60


def due_for_outcome(documents: list[dict], now: datetime) -> list[dict]:
    """Executed proposals whose outcome is unmeasured and now due.

    A proposal is due when it is ``executed``, has no ``actual_outcome`` yet, and
    at least :data:`OUTCOME_DELAY_MIN` sim-minutes have passed since ``executed_at``.
    """
    due: list[dict] = []
    cutoff = _utc(now) - timedelta(minutes=OUTCOME_DELAY_MIN)
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
        if not incident_id or status is None:
            return {**base, "measurable": False, "target": "incident",
                    "incident_id": incident_id, "reason": "target incident not observed"}
        if action_type == "resolve_incident":
            resolved = status == "resolved"
        else:  # contain_incident
            resolved = status in ("contained", "resolved")
        return {**base, "target": "incident", "incident_id": incident_id,
                "incident_status": status, "bottleneck_resolved": resolved}

    if action_type == "reassign_gate":
        flight_id = parameters.get("flight_id")
        flight = (getattr(state, "flights", {}) or {}).get(flight_id)
        gate = getattr(flight, "gate", None) if flight is not None else None
        expected_gate = parameters.get("gate_id")
        if flight is None or not expected_gate:
            return {**base, "measurable": False, "target": "flight_gate",
                    "flight_id": flight_id, "gate": gate,
                    "reason": "target flight or requested gate not observed"}
        return {**base, "target": "flight_gate", "flight_id": flight_id,
                "gate": gate, "requested_gate": expected_gate,
                "bottleneck_resolved": gate == expected_gate}

    if action_type == "open_security_lane":
        terminal = parameters.get("terminal")
        terminal = f"Terminal {terminal}" if terminal in {"A", "B", "C"} else terminal
        sec = (getattr(state, "security", {}) or {}).get(terminal)
        observed_at = getattr(sec, "last_updated", None)
        if observed_at is None:
            return {**base, "measurable": False, "target": "security",
                    "terminal": terminal, "reason": "checkpoint not observed"}
        wait = getattr(sec, "observed_wait_minutes", None)
        lanes = getattr(sec, "open_lanes", None) if sec is not None else None
        return {**base, "target": "security", "terminal": terminal,
                "current_wait_minutes": wait, "open_lanes": lanes,
                "observed_at": observed_at.isoformat()}

    # No measurement model yet for this action type — say so honestly.
    return {"measured_sim_minutes": OUTCOME_DELAY_MIN, "measurable": False,
            "reason": f"no outcome model for action_type {action_type!r}"}


# ── Baseline / counterfactual attribution (G8, A58) ───────────────────────────

ATTRIBUTION_VERSION = "attribution-v1"
WAITING_FOR_GATE = frozenset({"approaching", "holding", "landed"})
MAX_CONTROLS = 50


def _terminal_name(value: object) -> object:
    return f"Terminal {value}" if value in {"A", "B", "C"} else value


def _observed_security(state) -> dict[str, dict]:
    observed: dict[str, dict] = {}
    for name, sec in (getattr(state, "security", {}) or {}).items():
        at = getattr(sec, "last_updated", None)
        wait = getattr(sec, "observed_wait_minutes", None)
        if at is not None and isinstance(wait, (int, float)) and not isinstance(wait, bool):
            observed[name] = {"wait": float(wait), "at": _utc(at).isoformat()}
    return observed


def observe_baseline(action_type: str, parameters: dict, state, now: datetime,
                     confidence: float | None = None) -> dict | None:
    """Pre-action observation of the target plus untreated comparable units.

    Returns ``None`` for action types without a measurement model. The
    ``predicted`` block holds the engine's ex-ante expectation in the same units
    as the attributed effect, so prediction and outcome can be compared.
    """
    parameters = parameters or {}
    base = {"version": ATTRIBUTION_VERSION, "observed_at": _utc(now).isoformat()}
    if action_type == "open_security_lane":
        terminal = _terminal_name(parameters.get("terminal"))
        observed = _observed_security(state)
        treated = observed.get(terminal)
        lanes = getattr((getattr(state, "security", {}) or {}).get(terminal), "open_lanes", None)
        new_lanes = parameters.get("new_lane_count") or ((lanes or 0) + 1)
        predicted = None
        if treated is not None and isinstance(new_lanes, (int, float)) and new_lanes > 1:
            # Same M/M/c-style proxy as ranking.py: one more lane removes 1/new of the wait.
            predicted = {"metric": "security_wait_minutes", "delta": -treated["wait"] / float(new_lanes)}
        return {**base, "metric": "security_wait_minutes", "target": terminal,
                "treated": treated, "controls": {k: v for k, v in observed.items() if k != terminal},
                "predicted": predicted}
    if action_type == "reassign_gate":
        flight_id = parameters.get("flight_id")
        flights = getattr(state, "flights", {}) or {}
        flight = flights.get(flight_id)
        controls = sorted(fid for fid, f in flights.items()
                          if fid != flight_id and getattr(f, "gate", None) is None
                          and getattr(f, "status", None) in WAITING_FOR_GATE)[:MAX_CONTROLS]
        treated = None if flight is None else int(getattr(flight, "gate", None) == parameters.get("gate_id"))
        return {**base, "metric": "flight_gated", "target": flight_id, "treated": treated,
                "requested_gate": parameters.get("gate_id"), "controls": controls, "predicted": _binary_prediction(confidence)}
    if action_type in ("resolve_incident", "contain_incident"):
        incident_id = parameters.get("incident_id")
        incidents = getattr(state, "active_incidents", {}) or {}
        target = incidents.get(incident_id)
        success = {"resolved"} if action_type == "resolve_incident" else {"contained", "resolved"}
        status = target.get("status") if isinstance(target, dict) else None
        controls = sorted(iid for iid, inc in incidents.items()
                          if iid != incident_id and isinstance(inc, dict)
                          and inc.get("status") not in success)[:MAX_CONTROLS]
        return {**base, "metric": "incident_resolved", "target": incident_id,
                "treated": None if status is None else int(status in success),
                "controls": controls, "success_statuses": sorted(success),
                "predicted": _binary_prediction(confidence)}
    return None


def _binary_prediction(confidence: float | None) -> dict | None:
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
        return None
    return {"metric": "success_probability", "probability": max(0.0, min(1.0, float(confidence)))}


def _not_eligible(method: str, reason: str, **fields) -> dict:
    return {"version": ATTRIBUTION_VERSION, "method": method, "calibration_eligible": False,
            "causal_claim": False, "reason": reason, **fields}


def attribute(baseline: dict | None, measured: dict, post: dict) -> dict:
    """Attribute the measured change to the action using the untreated arm.

    ``post`` carries the fresh post-action observations of the treated unit and
    of every baseline control (``treated`` and ``controls``), read at
    measurement time. The effect is ``treated_change - control_change``: the
    change beyond what comparable untreated units did over the same window.
    """
    if not baseline:
        return _not_eligible("none", "no pre-action baseline was captured")
    if not measured.get("measurable", False):
        return _not_eligible("none", measured.get("reason") or "outcome not measurable")
    metric = baseline.get("metric")
    if metric == "security_wait_minutes":
        before = baseline.get("treated")
        after = post.get("treated")
        if not before or not after:
            return _not_eligible("none", "treated checkpoint not observed before and after")
        if _parse(after.get("at")) is None or _parse(after["at"]) <= _parse(before["at"]):
            return _not_eligible("none", "treated observation not refreshed after execution")
        treated_change = after["wait"] - before["wait"]
        changes = []
        for name, pre in (baseline.get("controls") or {}).items():
            current = (post.get("controls") or {}).get(name)
            if current and _parse(current.get("at")) and _parse(current["at"]) > _parse(pre["at"]):
                changes.append(current["wait"] - pre["wait"])
        fields = {"metric": metric, "treated_before": before["wait"], "treated_after": after["wait"],
                  "treated_change": treated_change, "control_count": len(changes)}
        if not changes:
            return _not_eligible("pre_post", "no fresh untreated checkpoint for a counterfactual",
                                 counterfactual_after=before["wait"], attributed_effect=treated_change,
                                 **fields)
        control_change = sum(changes) / len(changes)
        return {"version": ATTRIBUTION_VERSION, "method": "difference_in_differences",
                "calibration_eligible": baseline.get("predicted") is not None, "causal_claim": False,
                **fields, "control_change": control_change,
                "counterfactual_after": before["wait"] + control_change,
                "attributed_effect": treated_change - control_change,
                "predicted_effect": (baseline.get("predicted") or {}).get("delta")}
    if metric in ("flight_gated", "incident_resolved"):
        treated = post.get("treated")
        if treated is None:
            return _not_eligible("none", "treated unit not observed after execution", metric=metric)
        outcomes = [int(v) for v in (post.get("controls") or {}).values() if v is not None]
        fields = {"metric": metric, "treated_before": baseline.get("treated"),
                  "treated_after": int(treated), "control_count": len(outcomes)}
        if not outcomes:
            prior = baseline.get("treated") or 0
            return _not_eligible("pre_post", "no observed untreated comparable unit for a counterfactual",
                                 counterfactual_after=prior, attributed_effect=int(treated) - prior, **fields)
        rate = sum(outcomes) / len(outcomes)
        return {"version": ATTRIBUTION_VERSION, "method": "untreated_control_rate",
                "calibration_eligible": baseline.get("predicted") is not None, "causal_claim": False,
                **fields, "control_rate": rate, "counterfactual_after": rate,
                "attributed_effect": int(treated) - rate,
                "predicted_probability": (baseline.get("predicted") or {}).get("probability")}
    return _not_eligible("none", f"no attribution model for metric {metric!r}")


def post_observation(baseline: dict | None, state, incident_status: dict | None = None) -> dict:
    """Read the fresh post-action observations needed by :func:`attribute`."""
    if not baseline:
        return {}
    metric = baseline.get("metric")
    if metric == "security_wait_minutes":
        observed = _observed_security(state)
        return {"treated": observed.get(baseline.get("target")),
                "controls": {name: observed.get(name) for name in (baseline.get("controls") or {})}}
    if metric == "flight_gated":
        flights = getattr(state, "flights", {}) or {}
        target = flights.get(baseline.get("target"))
        requested = baseline.get("requested_gate")
        return {"treated": None if target is None or not requested
                else int(getattr(target, "gate", None) == requested),
                "controls": {fid: (None if flights.get(fid) is None else int(getattr(flights[fid], "gate", None) is not None))
                             for fid in baseline.get("controls") or []}}
    if metric == "incident_resolved":
        statuses = incident_status or {}
        success = set(baseline.get("success_statuses") or ["resolved"])
        target = statuses.get(baseline.get("target"))
        return {"treated": None if target is None else int(target in success),
                "controls": {iid: (None if statuses.get(iid) is None else int(statuses[iid] in success))
                             for iid in baseline.get("controls") or []}}
    return {}

"""Pure shared effect core. No service imports, randomness, clock or persistence I/O."""

from __future__ import annotations

from typing import Any, Sequence

from pydantic import BaseModel, Field

from _common.airport_config import EffectParameters, load_airport_runtime_config
from _common.commands import action_command

EFFECT_MODEL_VERSION = "effects-v1"
MODELLED_ACTIONS = frozenset({
    "open_security_lane", "reassign_gate", "hold_connecting_flight", "delay_taxi",
    "ground_delay_program", "redirect_baggage", "contain_incident", "resolve_incident",
})
HOLDABLE = frozenset({"scheduled", "boarding", "approach"})


class Security(BaseModel):
    queue: float = Field(default=0, ge=0)
    lanes: int = Field(default=0, ge=0, le=20)
    arrivals_per_minute: float = Field(default=0, ge=0)
    wait: float = Field(default=0, ge=0)


class Flight(BaseModel):
    terminal: str = ""
    gate: str | None = None
    status: str = "scheduled"
    direction: str = "departure"
    delay: float = Field(default=0, ge=0)
    passengers: int = Field(default=0, ge=0)


class Gate(BaseModel):
    terminal: str
    occupant: str | None = None
    available: bool = True


class Bag(BaseModel):
    flight_id: str | None = None
    zone: str | None = None
    status: str = "sorting"


class EffectState(BaseModel):
    minute: int = 0
    security: dict[str, Security] = Field(default_factory=dict)
    gates: dict[str, Gate] = Field(default_factory=dict)
    flights: dict[str, Flight] = Field(default_factory=dict)
    bags: dict[str, Bag] = Field(default_factory=dict)
    baggage_zones: dict[str, float] = Field(default_factory=dict)
    incidents: dict[str, str] = Field(default_factory=dict)


class Action(BaseModel):
    action_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)


class EffectResult(BaseModel):
    effect_model_version: str = EFFECT_MODEL_VERSION
    baseline: EffectState
    projected: EffectState
    action_status: list[str]
    impact_value: float = 0
    cost_value: float = 0
    predictions: dict[str, dict[str, float | str]] = Field(default_factory=dict)


def parameters() -> EffectParameters:
    return load_airport_runtime_config().operations.effects.model_copy(deep=True)


def terminal_name(value: str) -> str:
    return value.removeprefix("Terminal ")


def security_throughput(lanes: int, params: EffectParameters | None = None) -> float:
    return max(0, lanes) * (params or parameters()).security_pax_per_lane_minute


def security_tick(queue: float, arrivals: float, lanes: int,
                  params: EffectParameters | None = None) -> tuple[float, float]:
    throughput = security_throughput(lanes, params)
    queue = max(0.0, queue + arrivals - throughput)
    # A closed checkpoint has a finite conservative wait, never zero for a queue.
    return queue, queue / max(1.0, throughput)


def runway_capacity(category: str, runways: int, wind_kt: float = 0) -> tuple[int, int]:
    ops = load_airport_runtime_config().operations
    cap = ops.weather_capacity.get(category, ops.weather_capacity["CAVOK"])
    usable = max(0, runways) if cap.runways >= 2 else min(max(0, runways), cap.runways)
    scale = usable / cap.runways
    dep, arr = int(cap.departure * scale), int(cap.arrival * scale)
    wind = ("crosswind_heavy" if wind_kt > ops.wind_thresholds_kt["crosswind_heavy"]
            else "crosswind" if wind_kt > ops.wind_thresholds_kt["crosswind"] else None)
    if wind:
        dep, arr = int(dep * ops.wind_reductions[wind]), int(arr * ops.wind_reductions[wind])
    return dep, arr


def _execute(state: EffectState, action: Action) -> str:
    kind, p = action.action_type, action.parameters
    if kind not in MODELLED_ACTIONS:
        return "no_effect_model"
    intent = action_command(kind, p)
    if intent is None:
        return "missing_parameters"
    p = intent.payload
    if kind == "open_security_lane":
        sec = state.security.get(terminal_name(p["terminal"]))
        if sec is None:
            return "target_not_observed"
        sec.lanes = p["lanes_open"]
    elif kind == "reassign_gate":
        flight, gate = state.flights.get(p["flight_id"]), state.gates.get(p["gate_id"])
        if flight is None or gate is None:
            return "target_not_observed"
        if not gate.available or gate.occupant not in (None, p["flight_id"]):
            return "unavailable"
        if flight.gate in state.gates:
            state.gates[flight.gate].occupant = None
        flight.gate, flight.terminal = p["gate_id"], gate.terminal
        gate.occupant = p["flight_id"]
    elif kind in {"hold_connecting_flight", "delay_taxi", "ground_delay_program"}:
        ids = p.get("flight_ids", [p.get("flight_id")])
        held = False
        for fid in ids:
            f = state.flights.get(fid)
            if f and f.status in HOLDABLE and (kind != "ground_delay_program" or f.direction == "departure"):
                f.delay += p.get("duration_min", p.get("stagger_minutes", 0))
                held = True
        if not held:
            return "unavailable"
    elif kind == "redirect_baggage":
        bag = state.bags.get(p["bag_id"])
        if bag is None or p["target_flight_id"] not in state.flights:
            return "target_not_observed"
        if bag.zone in state.baggage_zones:
            state.baggage_zones[bag.zone] = max(0, state.baggage_zones[bag.zone] - 1)
        bag.flight_id, bag.zone, bag.status = p["target_flight_id"], None, "redirected"
    else:
        iid = p["incident_id"]
        if iid not in state.incidents:
            return "target_not_observed"
        if state.incidents[iid] != "resolved":
            state.incidents[iid] = "resolved" if kind == "resolve_incident" else "contained"
    return "modelled"


def step(state: EffectState, actions: Sequence[Action] = (), *,
         params: EffectParameters | None = None) -> tuple[EffectState, list[str]]:
    """Advance one minute. Actions are applied once, at the start of this tick."""
    params = params or parameters()
    result = state.model_copy(deep=True)
    statuses = [_execute(result, a) for a in actions]
    for sec in result.security.values():
        sec.queue, sec.wait = security_tick(sec.queue, sec.arrivals_per_minute, sec.lanes, params)
    for name, sec in result.security.items():
        before = state.security[name]
        if before.queue > 0 and before.wait > 0:
            sec.wait = before.wait * sec.queue / before.queue * max(1, before.lanes) / max(1, sec.lanes)
    result.minute += 1
    return result, statuses


def apply_instant(state: EffectState, actions: list[Action]) -> tuple[EffectState, list[str]]:
    """Apply intervention commands without advancing queues (detailed-engine adapter)."""
    result = state.model_copy(deep=True)
    return result, [_execute(result, action) for action in actions]


def planning_window(interventions: list[dict], disruption: dict | None,
                    minute: int) -> tuple[float, int]:
    """Shared planning window policy. GDP holds do not reduce runway capacity."""
    cap, lanes = 1.0, 0
    if disruption and disruption["sim_minute"] <= minute < disruption["sim_minute"] + disruption["duration_minutes"]:
        cap = max(0.0, min(1.0, disruption["capacity_pct"]))
    for iv in interventions:
        if iv["action"] == "open_security_lanes" and iv["sim_minute"] <= minute < iv["sim_minute"] + iv["duration_minutes"]:
            lanes += max(0, int(iv["params"].get("lanes", 1)))
    return cap, lanes


def planning_actions(interventions: list[dict], minute: int, state: EffectState) -> list[Action]:
    actions = []
    for iv in interventions:
        if iv["sim_minute"] != minute:
            continue
        p, kind = iv["params"], iv["action"]
        if kind == "gdp_start":
            # cap_pct is a legacy demand-metering input, not runway degradation.
            metered_fraction = max(0, min(1, float(p.get("cap_pct", 0.7))))
            hold = int(p.get("hold_minutes", (1 - metered_fraction) * iv["duration_minutes"]))
            ids = p.get("flight_ids", [fid for fid, f in state.flights.items() if f.direction == "departure"])
            if hold > 0 and ids and not any(x["action"] == "gdp_end" and x["sim_minute"] == minute for x in interventions):
                actions.append(Action(action_type="ground_delay_program", parameters={"flight_ids": ids, "stagger_minutes": hold}))
        elif kind == "gate_swap":
            fid = p.get("flight_id") or next((fid for fid, f in state.flights.items() if not f.gate), None)
            gid = p.get("gate_id") or next((gid for gid, g in state.gates.items() if g.available and g.occupant is None), None)
            if fid and gid:
                actions.append(Action(action_type="reassign_gate", parameters={"flight_id": fid, "gate_id": gid}))
    return actions


def apply(actions: list[Action], state: EffectState, horizon: int, *,
          params: EffectParameters | None = None,
          factors: dict[str, float] | None = None) -> EffectResult:
    """Project against an untreated arm using the same deterministic tick inputs."""
    if not 1 <= horizon <= 1440:
        raise ValueError("horizon must be in [1, 1440] simulated minutes")
    params = params or parameters()
    base, projected = state.model_copy(deep=True), state.model_copy(deep=True)
    statuses: list[str] = []
    for minute in range(horizon):
        base, _ = step(base, params=params)
        projected, current = step(projected, actions if minute == 0 else [], params=params)
        if minute == 0:
            statuses = current
    def factor(kind: str) -> float:
        return max(params.calibration_factor_min, min(
            params.calibration_factor_max, (factors or {}).get(kind, 1.0)))
    impact, cost, predictions = 0.0, params.cost_floor, {}
    credited: set[tuple[str, str]] = set()
    hold_cost_added = False
    for action, status in zip(actions, statuses):
        if status != "modelled":
            continue
        kind, p = action.action_type, action.parameters
        probability = min(1.0, params.success_probability * factor(kind))
        if kind == "open_security_lane":
            name = terminal_name(p.get("terminal", ""))
            delta = (projected.security[name].wait - base.security[name].wait) * factor(kind)
            predictions[kind] = {"metric": "security_wait_minutes", "delta": delta}
            if ("security", name) not in credited:
                impact += max(0, -delta) * state.security[name].queue
                credited.add(("security", name))
            cost += params.lane_cost
        elif kind == "reassign_gate":
            fid = p.get("flight_id", p.get("outbound_flight"))
            changed = state.flights[fid].gate != projected.flights[fid].gate
            predictions[kind] = {"metric": "success_probability", "probability": probability if changed else 0.0}
            if ("flight", fid) not in credited:
                impact += changed * probability * params.gate_slack_minutes * state.flights[fid].passengers
                credited.add(("flight", fid))
        elif kind in {"contain_incident", "resolve_incident"}:
            changed = state.incidents[p["incident_id"]] != projected.incidents[p["incident_id"]]
            predictions[kind] = {"metric": "success_probability", "probability": probability if changed else 0.0}
            if ("incident", p["incident_id"]) not in credited:
                impact += changed * probability * horizon
                credited.add(("incident", p["incident_id"]))
            cost += params.incident_cost
        elif kind == "redirect_baggage":
            # One bag rerouted, no invented queue-wide or passenger benefit.
            if ("bag", p["bag_id"]) not in credited:
                impact += factor(kind)
                credited.add(("bag", p["bag_id"]))
            cost += params.baggage_cost
        elif not hold_cost_added:
            cost += sum(max(0, f.delay - base.flights[fid].delay) for fid, f in projected.flights.items())
            hold_cost_added = True
    return EffectResult(baseline=base, projected=projected, action_status=statuses,
                        impact_value=impact, cost_value=cost, predictions=predictions)

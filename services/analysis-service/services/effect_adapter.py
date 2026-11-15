"""Map analysis snapshots to the shared G4 effect contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

from _common.effects import (
    Action, Bag, EffectResult, EffectState, Flight, Gate, Security, apply, parameters,
    security_throughput, terminal_name,
)
from services import calibration

if TYPE_CHECKING:
    from services.state import OperationalState


def from_operational(state: OperationalState, bag_id: str | None = None) -> EffectState:
    params = parameters()
    security = {}
    for name, sec in getattr(state, "security", {}).items():
        wait = max(getattr(sec, "observed_wait_minutes", 0), getattr(sec, "forecast_wait_minutes", 0))
        throughput = security_throughput(sec.open_lanes, params)
        security[terminal_name(name)] = Security(
            queue=getattr(sec, "queue_depth", 0) or wait * max(1, throughput), lanes=sec.open_lanes,
            wait=wait, arrivals_per_minute=throughput,
        )
    flights = {fid: Flight(terminal=terminal_name(getattr(f, "terminal", "") or ""), gate=f.gate,
                           status=f.status, direction=getattr(f, "flight_type", "departure"), delay=getattr(f, "delay_minutes", 0),
                           passengers=getattr(f, "passenger_count", 0)) for fid, f in getattr(state, "flights", {}).items()}
    occupants = {f.gate: fid for fid, f in flights.items() if f.gate and f.status not in {"completed", "cancelled"}}
    gates = {gid: Gate(terminal=terminal_name(g.get("terminal", "")), occupant=occupants.get(gid),
                       available=g.get("status") not in {"closed", "maintenance", "offline"})
             for gid, g in getattr(state, "gates", {}).items()}
    # Only the selected bag enters the compact core; queue totals remain unsampled.
    targets = getattr(state, "baggage_targets", {})
    bag_id = bag_id if bag_id is not None else next(iter(targets), None)
    bags = {bag_id: Bag.model_validate(targets[bag_id])} if bag_id in targets else {}
    return EffectState(security=security, flights=flights, gates=gates, bags=bags,
                       baggage_zones={z: v.current_count for z, v in getattr(state, "baggage_zones", {}).items()},
                       incidents={iid: inc.get("status", "active") for iid, inc in getattr(state, "active_incidents", {}).items()})


def project(state: OperationalState, action_type: str, action_parameters: dict,
            horizon: int | None = None) -> tuple[EffectResult, dict]:
    compact = from_operational(state, action_parameters.get("bag_id"))
    params = parameters()
    horizon = horizon if horizon is not None else params.prediction_horizon_minutes
    factor = calibration.factors(action_type).impact
    action = Action(action_type=action_type, parameters=action_parameters)
    result = apply([action], compact, horizon, params=params, factors={action_type: factor})
    replay = {"state": compact.model_dump(mode="json"), "actions": [action.model_dump(mode="json")],
              "horizon": horizon, "params": params.model_dump(mode="json"), "factors": {action_type: factor},
              "tick_number": getattr(state, "tick_number", None),
              "sim_time": state.sim_time.isoformat() if getattr(state, "sim_time", None) else None}
    return result, replay


def patch_operational(shadow: OperationalState, projected: EffectState) -> None:
    for name, sec in shadow.security.items():
        item = projected.security[terminal_name(name)]
        sec.queue_depth, sec.open_lanes = int(item.queue), item.lanes
        sec.forecast_wait_minutes = sec.observed_wait_minutes = item.wait
    for fid, flight in shadow.flights.items():
        item = projected.flights[fid]
        flight.delay_minutes, flight.gate = item.delay, item.gate
        flight.terminal = f"Terminal {item.terminal}" if item.terminal else None
    for iid, status in projected.incidents.items():
        shadow.active_incidents[iid]["status"] = status
    for zone, count in projected.baggage_zones.items():
        item = shadow.baggage_zones[zone]
        item.current_count = int(count)
        item.utilisation_pct = count / item.capacity * 100 if item.capacity else 0

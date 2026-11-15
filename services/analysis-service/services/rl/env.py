"""Gymnasium environment for airport operations optimisation.

P5-1-1: State space, action space, and reward function definition.
P5-1-2: GymEnvironment wrapper around the simulation engine.

The environment wraps the analysis-service's OperationalState and what-if
engine to provide a standard Gymnasium interface. Each step applies one
action and advances the shadow simulation by 1 sim-minute.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from _common.effects import (Action, EffectState, Flight, Gate, Security, Bag,
                             EFFECT_MODEL_VERSION, parameters, security_throughput, step, terminal_name)

logger = logging.getLogger(__name__)

# ── P5-1-1: State, action, and reward definition ────────────

# State space: 22 continuous dimensions
STATE_DIM = 22
STATE_LABELS = [
    # Security queue depths (3)
    "security_queue_A", "security_queue_B", "security_queue_C",
    # Security forecast waits (3)
    "security_wait_A", "security_wait_B", "security_wait_C",
    # Free gates per terminal (3)
    "free_gates_A", "free_gates_B", "free_gates_C",
    # Flight metrics (7)
    "total_delay_minutes",
    "flights_scheduled", "flights_boarding", "flights_departed",
    "flights_approaching", "flights_holding", "flights_landed",
    # Vehicle/weather/incidents (4)
    "vehicle_util_avg",
    "weather_category",  # ordinal: CAVOK=0, VMC=1, IMC=2, LIFR=3
    "active_incident_count",
    "active_bottleneck_count",
    # Runway (1)
    "runway_capacity_pct",
    # Time feature (1)
    "sim_hour",
]

# Action space: 7 discrete actions
NUM_ACTIONS = 7
ACTION_NAMES = [
    "no_action",
    "open_security_lane",
    "reassign_gate",
    "hold_connecting_flight",
    "fast_track_passengers",
    "redirect_baggage",
    "redistribute_vehicles",
]

WEATHER_ORDINAL = {"CAVOK": 0, "VMC": 1, "IMC": 2, "LIFR": 3}

FLIGHT_STATUS_GROUPS = {
    "scheduled": ("scheduled",),
    "boarding": ("boarding", "gate_open"),
    "departed": ("departed", "airborne", "taxiing_out"),
    "approaching": ("approach", "approaching", "final_approach"),
    "holding": ("holding",),
    "landed": ("landed", "at_gate", "taxiing", "taxiing_in"),
}

# Episode length in sim-minutes
EPISODE_LENGTH = 120

# Reward weights
REWARD_DELAY_WEIGHT = -0.01  # per delay-minute delta
REWARD_MISSED_CONN = -10.0  # per missed connection
REWARD_BOTTLENECK_ACTIVE = -5.0  # per active bottleneck
REWARD_BOTTLENECK_RESOLVED = 10.0  # per resolved bottleneck


# ── P5-1-2: Gymnasium environment ────────────────────────────


class AirportOpsEnv(gym.Env):
    """Gymnasium environment wrapping the airport operational state.

    Each step:
    1. Applies the selected action to a shadow state
    2. Advances the shadow simulation by 1 sim-minute
    3. Returns the new observation, reward, and termination flags

    The environment does NOT produce Kafka events or write to Neo4j.
    """

    metadata = {"render_modes": []}

    def __init__(
        self,
        initial_state: dict | None = None,
        episode_length: int = EPISODE_LENGTH,
    ) -> None:
        super().__init__()

        self.episode_length = episode_length

        # Observation: 22 continuous features
        self.observation_space = spaces.Box(
            low=np.full(STATE_DIM, -np.inf, dtype=np.float32),
            high=np.full(STATE_DIM, np.inf, dtype=np.float32),
            dtype=np.float32,
        )

        # Action: 7 discrete choices
        self.action_space = spaces.Discrete(NUM_ACTIONS)

        # State
        self._initial_state = initial_state
        self._state: dict | None = None
        self._step_count = 0
        self._prev_delay = 0.0
        self._prev_bottlenecks = 0
        self._prev_wait = 0.0

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        """Reset the environment to a fresh state."""
        super().reset(seed=seed)

        if options and "state" in options:
            self._state = copy.deepcopy(options["state"])
        elif self._initial_state:
            self._state = copy.deepcopy(self._initial_state)
        else:
            self._state = _default_state()

        self._step_count = 0
        self._prev_delay = self._get_total_delay()
        self._prev_bottlenecks = self._state.get("bottleneck_count", 0)
        self._prev_wait = sum(s.get("forecast_wait_minutes", 0) for s in self._state.get("security", {}).values())

        obs = self._get_obs()
        return obs, {}

    def step(
        self, action: int,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Apply action, advance 1 sim-minute, return (obs, reward, term, trunc, info)."""
        assert self.action_space.contains(action)

        # Apply action to shadow state
        action_effect = _advance_shared(self._state, action)

        self._step_count += 1

        # Compute reward
        new_delay = self._get_total_delay()
        new_bottlenecks = self._state.get("bottleneck_count", 0)

        reward = 0.0
        # Delay delta penalty
        delay_delta = new_delay - self._prev_delay
        reward += delay_delta * REWARD_DELAY_WEIGHT
        wait = sum(s.get("forecast_wait_minutes", 0) for s in self._state.get("security", {}).values())
        reward += (wait - self._prev_wait) * REWARD_DELAY_WEIGHT
        if action == 1 and action_effect == "modelled":
            reward -= parameters().lane_cost * abs(REWARD_DELAY_WEIGHT)
        self._prev_wait = wait

        # Bottleneck change
        bottleneck_delta = new_bottlenecks - self._prev_bottlenecks
        if bottleneck_delta > 0:
            reward += bottleneck_delta * REWARD_BOTTLENECK_ACTIVE
        elif bottleneck_delta < 0:
            reward += abs(bottleneck_delta) * REWARD_BOTTLENECK_RESOLVED

        self._prev_delay = new_delay
        self._prev_bottlenecks = new_bottlenecks

        # Termination
        terminated = False
        truncated = self._step_count >= self.episode_length

        obs = self._get_obs()
        info = {
            "effect_model_version": EFFECT_MODEL_VERSION,
            "action_name": ACTION_NAMES[action],
            "action_effect": action_effect,
            "step": self._step_count,
            "total_delay": new_delay,
            "bottleneck_count": new_bottlenecks,
        }

        return obs, reward, terminated, truncated, info

    def _get_obs(self) -> np.ndarray:
        """Extract observation vector from current state."""
        s = self._state
        if s is None:
            return np.zeros(STATE_DIM, dtype=np.float32)

        security = s.get("security", {})
        free_gates = s.get("free_gates", {})
        flights = s.get("flights", {})

        # Count flights by status group
        flight_counts = {k: 0 for k in FLIGHT_STATUS_GROUPS}
        for f in flights.values():
            status = f.get("status", "scheduled")
            for group, statuses in FLIGHT_STATUS_GROUPS.items():
                if status in statuses:
                    flight_counts[group] += 1
                    break

        # Vehicle util
        vehicles = s.get("vehicles", {})
        v_utils = [v.get("utilisation_pct", 0) for v in vehicles.values()]
        vehicle_util_avg = float(np.mean(v_utils)) if v_utils else 0.0

        weather_cat = WEATHER_ORDINAL.get(
            s.get("weather", {}).get("category", "CAVOK"), 0,
        )

        sim_time = s.get("sim_time")
        sim_hour = sim_time.hour if isinstance(sim_time, datetime) else 12.0

        obs = np.array([
            security.get("Terminal A", {}).get("queue_depth", 0),
            security.get("Terminal B", {}).get("queue_depth", 0),
            security.get("Terminal C", {}).get("queue_depth", 0),
            security.get("Terminal A", {}).get("forecast_wait_minutes", 0),
            security.get("Terminal B", {}).get("forecast_wait_minutes", 0),
            security.get("Terminal C", {}).get("forecast_wait_minutes", 0),
            free_gates.get("Terminal A", 14),
            free_gates.get("Terminal B", 14),
            free_gates.get("Terminal C", 14),
            self._get_total_delay(),
            flight_counts.get("scheduled", 0),
            flight_counts.get("boarding", 0),
            flight_counts.get("departed", 0),
            flight_counts.get("approaching", 0),
            flight_counts.get("holding", 0),
            flight_counts.get("landed", 0),
            vehicle_util_avg,
            float(weather_cat),
            float(len(s.get("incidents", {}))),
            float(s.get("bottleneck_count", 0)),
            s.get("weather", {}).get("runway_capacity_pct", 100.0),
            float(sim_hour),
        ], dtype=np.float32)

        return obs

    def _get_total_delay(self) -> float:
        """Sum of delay minutes across all active flights."""
        if not self._state:
            return 0.0
        return sum(
            f.get("delay_minutes", 0)
            for f in self._state.get("flights", {}).values()
            if f.get("status") not in ("completed", "cancelled")
        )


# ── State manipulation helpers ───────────────────────────────


def state_from_operational(op_state, active_bottleneck_count: int = 0) -> dict:
    """Convert an OperationalState to a lightweight dict for the RL env.

    This creates a snapshot that can be deep-copied for shadow simulation
    without referencing the original OperationalState object.
    """
    security = {}
    for t, sec in op_state.security.items():
        security[t] = {
            "queue_depth": sec.queue_depth,
            "forecast_wait_minutes": max(sec.forecast_wait_minutes, sec.observed_wait_minutes),
            "open_lanes": sec.open_lanes,
        }

    flights = {}
    for fid, f in op_state.flights.items():
        flights[fid] = {
            "flight_id": fid,
            "status": f.status,
            "flight_type": f.flight_type,
            "gate": f.gate,
            "terminal": f.terminal,
            "delay_minutes": f.delay_minutes,
            "passenger_count": f.passenger_count,
        }

    free_gates = op_state.get_free_gates_by_terminal()

    vehicles = {}
    for vtype, v in op_state.vehicles.items():
        vehicles[vtype] = {
            "total": v.total,
            "dispatched": v.dispatched,
            "utilisation_pct": v.utilisation_pct,
        }

    from services.effect_adapter import from_operational

    return {
        "effect_state": from_operational(op_state).model_dump(mode="json"),
        "sim_time": op_state.sim_time,
        "security": security,
        "flights": flights,
        "free_gates": free_gates,
        "vehicles": vehicles,
        "weather": {
            "category": op_state.weather.category,
            "runway_capacity_pct": op_state.weather.runway_capacity_pct,
        },
        "incidents": dict(op_state.active_incidents),
        "bottleneck_count": active_bottleneck_count,
    }


def _default_state() -> dict:
    """Create a minimal default state for standalone training."""
    return {
        "sim_time": datetime(2024, 6, 15, 8, 0, 0),
        "security": {
            t: {"queue_depth": 360, "forecast_wait_minutes": 30.0, "open_lanes": 4}
            for t in ("Terminal A", "Terminal B", "Terminal C")
        },
        "flights": {},
        "free_gates": {
            t: 10 for t in ("Terminal A", "Terminal B", "Terminal C")
        },
        "vehicles": {},
        "weather": {"category": "CAVOK", "runway_capacity_pct": 100.0},
        "incidents": {},
        "bottleneck_count": 3,
    }


def _compact(state: dict) -> EffectState:
    if "effect_state" in state:
        return EffectState.model_validate(state["effect_state"])
    params = parameters()
    security = {terminal_name(t): Security(
        queue=sec.get("queue_depth", 0), lanes=sec.get("open_lanes", 4),
        wait=sec.get("forecast_wait_minutes", 0),
        arrivals_per_minute=sec.get("arrivals_per_minute", security_throughput(sec.get("open_lanes", 4), params)))
        for t, sec in state.get("security", {}).items()}
    return EffectState(security=security, flights={fid: Flight(
        terminal=terminal_name(f.get("terminal") or ""), gate=f.get("gate"), status=f.get("status", "scheduled"),
        direction=f.get("flight_type", "departure"), delay=f.get("delay_minutes", 0), passengers=f.get("passenger_count", 0))
        for fid, f in state.get("flights", {}).items()},
        gates={gid: Gate.model_validate(g) for gid, g in state.get("gates", {}).items()},
        bags={bid: Bag.model_validate(b) for bid, b in state.get("bags", {}).items()},
        incidents={iid: inc.get("status", "active") for iid, inc in state.get("incidents", {}).items()})


def _choose_action(compact: EffectState, action: int) -> Action:
    p = {}
    if action == 1 and compact.security:
        terminal = max(compact.security, key=lambda t: compact.security[t].queue)
        p = {"terminal": terminal, "lanes_open": min(20, compact.security[terminal].lanes + 1)}
    elif action == 2:
        for fid, flight in compact.flights.items():
            if not flight.gate and flight.status in {"approach", "approaching", "holding", "landed"}:
                gate = next((gid for gid, g in compact.gates.items() if g.available and g.occupant is None), None)
                if gate:
                    p = {"flight_id": fid, "gate_id": gate}
                    break
    elif action == 3:
        fid = next((fid for fid, f in compact.flights.items() if f.status == "boarding"), None)
        if fid:
            p = {"flight_id": fid, "hold_minutes": 5}
    elif action == 5:
        bag = next(iter(compact.bags), None)
        if bag:
            target = next((fid for fid in compact.flights if fid != compact.bags[bag].flight_id), None)
            if target:
                p = {"bag_id": bag, "target_flight_id": target}
    return Action(action_type=ACTION_NAMES[action], parameters=p)


def _advance_shared(state: dict, action: int) -> str:
    from datetime import timedelta

    compact = _compact(state)
    projected, statuses = step(compact, [_choose_action(compact, action)])
    state["effect_state"] = projected.model_dump(mode="json")
    state["bottleneck_count"] = (
        sum(s.wait > 15 for s in projected.security.values())
        + sum(f.status in {"approach", "approaching", "holding", "landed"} and not f.gate
              for f in projected.flights.values())
        + sum(status not in {"resolved", "contained"} for status in projected.incidents.values())
    )
    for name, sec in state.get("security", {}).items():
        item = projected.security[terminal_name(name)]
        sec.update(queue_depth=item.queue, open_lanes=item.lanes, forecast_wait_minutes=item.wait)
    for fid, f in state.get("flights", {}).items():
        item = projected.flights[fid]
        f.update(delay_minutes=item.delay, gate=item.gate, terminal=f"Terminal {item.terminal}")
    state["free_gates"] = {f"Terminal {t}": sum(g.available and g.occupant is None
                                               for g in projected.gates.values() if g.terminal == t)
                           for t in projected.security}
    if isinstance(state.get("sim_time"), datetime):
        state["sim_time"] += timedelta(minutes=1)
    return statuses[0]

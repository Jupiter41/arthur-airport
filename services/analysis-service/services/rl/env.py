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
from datetime import datetime, timedelta
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

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
    "approaching": ("approaching", "final_approach"),
    "holding": ("holding",),
    "landed": ("landed", "at_gate", "taxiing_in"),
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

        obs = self._get_obs()
        return obs, {}

    def step(
        self, action: int,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Apply action, advance 1 sim-minute, return (obs, reward, term, trunc, info)."""
        assert self.action_space.contains(action)

        # Apply action to shadow state
        action_effect = _apply_action(self._state, action)

        # Advance simulation by 1 sim-minute
        _advance_sim_minute(self._state)

        self._step_count += 1

        # Compute reward
        new_delay = self._get_total_delay()
        new_bottlenecks = self._state.get("bottleneck_count", 0)

        reward = 0.0
        # Delay delta penalty
        delay_delta = new_delay - self._prev_delay
        reward += delay_delta * REWARD_DELAY_WEIGHT

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


def state_from_operational(op_state) -> dict:
    """Convert an OperationalState to a lightweight dict for the RL env.

    This creates a snapshot that can be deep-copied for shadow simulation
    without referencing the original OperationalState object.
    """
    security = {}
    for t, sec in op_state.security.items():
        security[t] = {
            "queue_depth": sec.queue_depth,
            "forecast_wait_minutes": sec.forecast_wait_minutes,
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

    return {
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
        "bottleneck_count": 0,  # set by caller
    }


def _default_state() -> dict:
    """Create a minimal default state for standalone training."""
    return {
        "sim_time": datetime(2024, 6, 15, 8, 0, 0),
        "security": {
            t: {"queue_depth": 20, "forecast_wait_minutes": 5.0, "open_lanes": 4}
            for t in ("Terminal A", "Terminal B", "Terminal C")
        },
        "flights": {},
        "free_gates": {
            t: 10 for t in ("Terminal A", "Terminal B", "Terminal C")
        },
        "vehicles": {},
        "weather": {"category": "CAVOK", "runway_capacity_pct": 100.0},
        "incidents": {},
        "bottleneck_count": 0,
    }


def _apply_action(state: dict, action: int) -> str:
    """Apply an action to the shadow state. Returns a description."""
    if action == 0:
        return "no_action"

    elif action == 1:  # open_security_lane
        # Find terminal with longest queue
        sec = state.get("security", {})
        worst = max(sec.items(), key=lambda kv: kv[1].get("queue_depth", 0))
        t_name = worst[0]
        sec[t_name]["open_lanes"] = min(8, sec[t_name].get("open_lanes", 4) + 1)
        # Reduce forecast wait by ~15%
        sec[t_name]["forecast_wait_minutes"] *= 0.85
        return f"opened_lane_{t_name}"

    elif action == 2:  # reassign_gate
        # Find a flight needing gate and assign from free pool
        for fid, f in state.get("flights", {}).items():
            if f.get("status") in ("approaching", "holding", "landed") and not f.get("gate"):
                best_terminal = max(
                    state.get("free_gates", {}).items(),
                    key=lambda kv: kv[1],
                )
                if best_terminal[1] > 0:
                    f["gate"] = f"reassigned_{best_terminal[0]}"
                    f["terminal"] = best_terminal[0]
                    state["free_gates"][best_terminal[0]] -= 1
                    return f"reassigned_gate_{fid[:8]}"
        return "no_gate_needed"

    elif action == 3:  # hold_connecting_flight
        # Reduce delay for approaching flights (simulates hold)
        held = 0
        for f in state.get("flights", {}).values():
            if f.get("status") == "boarding" and f.get("delay_minutes", 0) < 15:
                f["delay_minutes"] = f.get("delay_minutes", 0) + 5
                held += 1
                if held >= 2:
                    break
        return f"held_{held}_flights"

    elif action == 4:  # fast_track_passengers
        # Reduce security queue depth in worst terminal
        sec = state.get("security", {})
        worst = max(sec.items(), key=lambda kv: kv[1].get("queue_depth", 0))
        t_name = worst[0]
        sec[t_name]["queue_depth"] = max(0, sec[t_name].get("queue_depth", 0) - 10)
        return f"fast_tracked_{t_name}"

    elif action == 5:  # redirect_baggage
        # Symbolic — reduce bottleneck pressure
        state["bottleneck_count"] = max(0, state.get("bottleneck_count", 0) - 1)
        return "redirected_baggage"

    elif action == 6:  # redistribute_vehicles
        # Balance vehicle utilisation
        for v in state.get("vehicles", {}).values():
            if v.get("utilisation_pct", 0) > 85:
                v["utilisation_pct"] = max(60, v["utilisation_pct"] - 15)
                v["dispatched"] = max(0, v.get("dispatched", 0) - 1)
        return "redistributed_vehicles"

    return "unknown_action"


def _advance_sim_minute(state: dict) -> None:
    """Advance the shadow simulation by 1 sim-minute.

    Applies lightweight stochastic updates to simulate time passing.
    This is a deliberately simplified model — not a full simulation engine.
    """
    rng = np.random.default_rng()

    # Advance sim_time
    if isinstance(state.get("sim_time"), datetime):
        state["sim_time"] += timedelta(minutes=1)

    # Security queues drift
    for sec in state.get("security", {}).values():
        lanes = sec.get("open_lanes", 4)
        throughput = lanes * 2  # ~2 pax/min/lane
        arrivals = int(rng.poisson(lam=max(3, throughput * 0.8)))
        sec["queue_depth"] = max(0, sec.get("queue_depth", 0) + arrivals - throughput)
        sec["forecast_wait_minutes"] = sec["queue_depth"] / max(1, throughput)

    # Flights: small chance of delay increase
    for f in state.get("flights", {}).values():
        if f.get("status") in ("approaching", "holding", "boarding"):
            if rng.random() < 0.05:
                f["delay_minutes"] = f.get("delay_minutes", 0) + rng.uniform(1, 5)

    # Vehicle utilisation drift
    for v in state.get("vehicles", {}).values():
        v["utilisation_pct"] = float(np.clip(
            v.get("utilisation_pct", 50) + rng.normal(0, 2), 0, 100,
        ))

    # Bottleneck stochastic creation/resolution
    if rng.random() < 0.02:
        state["bottleneck_count"] = state.get("bottleneck_count", 0) + 1
    if rng.random() < 0.05 and state.get("bottleneck_count", 0) > 0:
        state["bottleneck_count"] -= 1

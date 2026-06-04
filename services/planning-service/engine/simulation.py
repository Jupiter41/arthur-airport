"""In-memory planning simulation engine.

Runs a full day's airport operations entirely in-memory with no Kafka or
Neo4j writes. Given the same config, adapter data, and random seed, the
engine always produces the same output — essential for Monte Carlo reliability.

Target: simulate 1 full day in < 500ms.

P2.1 of ROADMAP_PLANNING.md.
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta

from adapters.base import AbstractAdapter
from _common.finance_constants import (
    DELAY_COST_PER_MINUTE_EUR,
    EU261_TIERS,
    GATE_FEE_PER_HOUR_EUR,
    LANDING_FEE_PER_TONNE_EUR,
    PAX_DEPARTURE_FEE_EUR,
)

from .infrastructure import InfrastructureConfig
from .interventions import Disruption, Intervention, aggregate_capacity_factor
from .results import DayResult

logger = logging.getLogger(__name__)

# ── Runway capacity by weather category ─────────────────────

RUNWAY_CAPACITY: dict[str, dict[str, int]] = {
    "CAVOK": {"arrival": 32, "departure": 32, "runways": 2},
    "VMC":   {"arrival": 28, "departure": 28, "runways": 2},
    "IMC":   {"arrival": 18, "departure": 16, "runways": 1},
    "LIFR":  {"arrival": 8,  "departure": 6,  "runways": 1},
}

# ── Wide body aircraft for turnaround buffer ────────────────

WIDE_BODY_TYPES = {"B77W", "A333", "A332", "B748", "A380"}
SEAT_MAP = {
    "B738": 189, "A320": 180, "A321": 220, "B77W": 396,
    "A333": 300, "E195": 120, "DH8D": 78, "AT75": 72,
}



# ── Flight states ───────────────────────────────────────────

TERMINAL_NAMES = ["A", "B", "C"]


def _apply_demand_multiplier(
    schedule: list[dict], multiplier: float, rng: random.Random,
) -> list[dict]:
    """Scale a daily schedule by ``multiplier`` (e.g. 1.2 → +20% demand).

    Strategy: scale per-flight pax linearly, then duplicate or sample flights
    to hit the target flight count. Duplicates are deep-copied with a unique
    ``flight_number`` suffix so downstream gate assignment treats them as
    separate operations.
    """
    if not schedule or multiplier <= 0:
        return schedule

    # Scale pax per flight (rounded to int for downstream consumers).
    scaled: list[dict] = []
    for f in schedule:
        copy = dict(f)
        if "pax_count" in copy:
            copy["pax_count"] = max(1, int(round(copy["pax_count"] * multiplier)))
        scaled.append(copy)

    target = int(round(len(scaled) * multiplier))
    if target == len(scaled):
        return scaled
    if target > len(scaled):
        # Duplicate flights up to target, with unique flight_numbers.
        extras_needed = target - len(scaled)
        for i in range(extras_needed):
            src = rng.choice(scaled[:len(schedule)])  # sample from originals
            dup = dict(src)
            dup["flight_number"] = f"{src.get('flight_number', 'XX')}D{i:03d}"
            scaled.append(dup)
        return scaled
    # Shrinking: sample without replacement.
    rng.shuffle(scaled)
    return scaled[:target]


def _expand_new_routes(
    new_routes: list[dict],
    sim_date: date,
    rng: random.Random,
) -> list[dict]:
    """Generate synthetic flight dicts for additive routes.

    Each entry of ``new_routes`` looks like::

        {
            "origin": "ART",
            "destination": "ZRH",
            "daily_flights": 2,
            "aircraft_type": "A320",
            "distance_km": 1200,        # optional, defaults to 1500
            "load_factor": 0.82,        # optional, defaults to 0.80
        }

    Departure times are uniformly spaced across the operating window
    (06:00–22:00) so they hit a mix of peak and off-peak hours. Flight
    numbers are deterministic per (route, rotation index) but unique within
    a day to avoid collisions with the base schedule.
    """
    generated: list[dict] = []
    for route in new_routes or []:
        dest = str(route.get("destination", "XXX")).upper()
        rotations = max(0, int(route.get("daily_flights", 0)))
        if rotations == 0:
            continue
        ac_type = str(route.get("aircraft_type", "A320"))
        distance_km = float(route.get("distance_km", 1500))
        load_factor = float(route.get("load_factor", 0.80))
        seats = SEAT_MAP.get(ac_type, 180)
        pax = max(1, int(round(seats * load_factor)))

        # Spread rotations across the 06:00–22:00 window.
        window_start_min = 6 * 60
        window_end_min = 22 * 60
        window_span = window_end_min - window_start_min
        spacing = window_span // max(1, rotations)
        for i in range(rotations):
            offset = window_start_min + spacing * i + rng.randint(0, max(1, spacing // 4))
            sched_dt = datetime.combine(sim_date, dt_time()) + timedelta(minutes=offset)
            generated.append({
                "flight_number": f"NR{dest}{i:02d}",
                "airline_code": "NR",
                "origin_iata": str(route.get("origin", "ART")),
                "destination_iata": dest,
                "aircraft_type": ac_type,
                "scheduled_departure": sched_dt.isoformat(),
                "pax_count": pax,
                "distance_km": distance_km,
            })
    return generated


@dataclass
class SimFlight:
    """In-memory flight state during planning simulation."""

    id: str
    flight_number: str
    airline_code: str
    origin_iata: str
    destination_iata: str
    aircraft_type: str
    scheduled_departure: datetime
    estimated_departure: datetime
    pax_count: int
    distance_km: float

    status: str = "scheduled"  # scheduled, boarding, departed, completed
    gate: str | None = None
    terminal: str | None = None
    delay_minutes: int = 0
    boarded_at: datetime | None = None
    departed_at: datetime | None = None
    cascade_depth: int = 0


@dataclass
class PlanningSimState:
    """Full airport state at one sim-minute. Mutable during tick processing."""

    sim_time: datetime = field(default_factory=datetime.now)
    flights: dict[str, SimFlight] = field(default_factory=dict)
    gate_occupancy: dict[str, str | None] = field(default_factory=dict)
    runway_departures_this_hour: int = 0
    runway_arrivals_this_hour: int = 0
    security_queues: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0})
    baggage_throughput: int = 0

    # Metrics accumulators
    total_delay_minutes: float = 0.0
    max_delay_minutes: float = 0.0
    max_cascade_depth: int = 0
    gate_conflicts: int = 0
    holding_events: int = 0
    missed_connections: int = 0
    security_wait_max: float = 0.0

    # Financial accumulators
    costs: dict[str, float] = field(default_factory=lambda: {
        "delay": 0.0, "eu261": 0.0, "landing_fees": 0.0,
        "gate_fees": 0.0, "incident": 0.0,
    })
    revenues: dict[str, float] = field(default_factory=lambda: {
        "pax_fees": 0.0, "landing_fees": 0.0, "gate_fees": 0.0,
    })

    # Hourly tracking for utilisation
    gate_hours_used: float = 0.0
    gate_hours_available: float = 0.0
    runway_ops_per_hour: list[int] = field(default_factory=list)
    peak_security_queue: dict[str, int] = field(default_factory=lambda: {"A": 0, "B": 0, "C": 0})


class PlanningSimEngine:
    """Fast in-memory airport simulation engine for capacity planning.

    Pure function of inputs: same config + adapter + seed → same output.

    The engine takes one mandatory schedule adapter and an optional weather
    adapter. When no weather adapter is provided, the schedule adapter is
    asked for weather as well (the legacy behaviour).
    """

    def __init__(
        self,
        adapter: AbstractAdapter,
        seed: int | None = None,
        *,
        weather_adapter: AbstractAdapter | None = None,
    ):
        self.adapter = adapter
        self.weather_adapter = weather_adapter or adapter
        self._base_seed = seed

    def run_day(
        self,
        sim_date: date,
        infrastructure: InfrastructureConfig,
        seed: int | None = None,
        *,
        demand_multiplier: float = 1.0,
        interventions: list[Intervention] | None = None,
        disruption: Disruption | None = None,
        new_routes: list[dict] | None = None,
    ) -> DayResult:
        """Simulate a single day end-to-end. No I/O, no Kafka, no Neo4j.

        ``demand_multiplier`` scales both the flight count and the per-flight
        passenger count linearly. A value of 1.2 simulates a 20% demand growth
        scenario without changing the underlying schedule data.

        ``interventions`` and ``disruption`` (1B — Counterfactual Delay Analysis)
        let callers replay the same day under different operator decisions.

        ``new_routes`` (optional) is a list of route additions appended to the
        base schedule *after* the demand multiplier is applied so the addition
        is purely additive. See :func:`_expand_new_routes` for the schema.
        """
        t0 = time.monotonic()
        rng = random.Random(seed if seed is not None else self._base_seed)

        schedule = self.adapter.get_daily_schedule(sim_date)
        weather_seq = self.weather_adapter.get_weather_sequence(sim_date)

        if demand_multiplier != 1.0 and demand_multiplier > 0:
            schedule = _apply_demand_multiplier(schedule, demand_multiplier, rng)

        if new_routes:
            schedule = list(schedule) + _expand_new_routes(new_routes, sim_date, rng)

        # 1B — gate_swap interventions add stand capacity for the entire run
        # (transient gate openings are not modelled; the largest delta wins).
        gate_swap_total = 0
        if interventions:
            for iv in interventions:
                if iv.action == "gate_swap":
                    gate_swap_total += int(iv.params.get("delta", 1))

        state = self._initialise_state(schedule, infrastructure, sim_date, rng)
        if gate_swap_total > 0:
            for i in range(gate_swap_total):
                state.gate_occupancy[f"X{i + 1:02d}"] = None
            state.gate_hours_available = len(state.gate_occupancy) * 24.0
        # Build hour→weather lookup
        weather_by_hour: dict[int, dict] = {}
        for w in weather_seq:
            weather_by_hour[w.get("hour", 0)] = w
        if not weather_by_hour:
            weather_by_hour[0] = {"hour": 0, "category": "CAVOK", "wind_speed_kt": 5, "visibility_m": 10000}

        # Simulate 24 hours in 1-minute ticks
        for minute in range(24 * 60):
            sim_time = datetime.combine(sim_date, dt_time()) + timedelta(minutes=minute)
            state.sim_time = sim_time
            hour = sim_time.hour
            weather = weather_by_hour.get(hour, weather_by_hour.get(0, {}))

            # Reset hourly runway counters
            if minute % 60 == 0:
                if minute > 0:
                    state.runway_ops_per_hour.append(
                        state.runway_departures_this_hour + state.runway_arrivals_this_hour
                    )
                state.runway_departures_this_hour = 0
                state.runway_arrivals_this_hour = 0

            self._tick(
                state, sim_time, weather, infrastructure, rng,
                interventions=interventions or [],
                disruption=disruption,
                minute=minute,
            )

        # Final hour
        state.runway_ops_per_hour.append(
            state.runway_departures_this_hour + state.runway_arrivals_this_hour
        )

        elapsed = time.monotonic() - t0
        logger.debug("Planning sim for %s completed in %.3fs", sim_date, elapsed)

        return self._build_result(state, sim_date, infrastructure, elapsed)

    def _initialise_state(
        self,
        schedule: list[dict],
        infra: InfrastructureConfig,
        sim_date: date,
        rng: random.Random,
    ) -> PlanningSimState:
        """Build initial state from schedule and infrastructure config."""
        state = PlanningSimState()

        # Create gate slots
        for terminal, count in infra.gates_per_terminal.items():
            for i in range(1, count + 1):
                gate_id = f"{terminal}{i:02d}"
                state.gate_occupancy[gate_id] = None

        state.gate_hours_available = len(state.gate_occupancy) * 24.0

        # Create flights from schedule
        terminals = list(infra.gates_per_terminal.keys())
        for i, fdict in enumerate(schedule):
            sched_str = fdict.get("scheduled_departure", "")
            try:
                sched_dt = datetime.fromisoformat(sched_str)
            except (ValueError, TypeError):
                sched_dt = datetime.combine(sim_date, dt_time(rng.randint(5, 22), rng.randint(0, 59)))

            terminal = terminals[i % len(terminals)] if terminals else "A"
            flight = SimFlight(
                id=f"pf-{i:04d}",
                flight_number=fdict.get("flight_number", f"XX{i:04d}"),
                airline_code=fdict.get("airline_code", "XX"),
                origin_iata=fdict.get("origin_iata", "ART"),
                destination_iata=fdict.get("destination_iata", "XXX"),
                aircraft_type=fdict.get("aircraft_type", "A320"),
                scheduled_departure=sched_dt,
                estimated_departure=sched_dt,
                pax_count=fdict.get("pax_count", 150),
                distance_km=fdict.get("distance_km", 1000),
                terminal=terminal,
            )
            state.flights[flight.id] = flight

            # Revenue from passenger fees
            state.revenues["pax_fees"] += flight.pax_count * PAX_DEPARTURE_FEE_EUR

        return state

    def _tick(
        self,
        state: PlanningSimState,
        sim_time: datetime,
        weather: dict,
        infra: InfrastructureConfig,
        rng: random.Random,
        *,
        interventions: list[Intervention] | None = None,
        disruption: Disruption | None = None,
        minute: int = 0,
    ) -> None:
        """Process one simulated minute."""
        category = weather.get("category", "CAVOK")
        wind_kt = weather.get("wind_speed_kt", 5)
        cap = RUNWAY_CAPACITY.get(category, RUNWAY_CAPACITY["CAVOK"])

        # Runway capacity adjusted for wind
        max_dep = cap["departure"]
        max_arr = cap["arrival"]
        active_runways = min(cap["runways"], infra.runway_count)
        if active_runways < 2 and infra.runway_count >= 2:
            max_dep = max_dep  # single runway ops due to weather
            max_arr = max_arr

        # Apply wind reductions
        if wind_kt > 35:
            max_dep = int(max_dep * 0.60)
            max_arr = int(max_arr * 0.60)
        elif wind_kt > 25:
            max_dep = int(max_dep * 0.85)
            max_arr = int(max_arr * 0.85)

        # 1B — apply interventions + baseline disruption to runway/security/gate capacity.
        cap_factor = 1.0
        extra_lanes = 0
        extra_gates = 0
        if interventions or disruption:
            cap_factor, extra_lanes, extra_gates = aggregate_capacity_factor(
                interventions or [], disruption, minute,
            )
            if cap_factor < 1.0:
                max_dep = int(max_dep * cap_factor)
                max_arr = int(max_arr * cap_factor)

        for flight in state.flights.values():
            if flight.status == "completed":
                continue

            sched = flight.estimated_departure
            minutes_to_departure = (sched - sim_time).total_seconds() / 60

            if flight.status == "scheduled":
                # Boarding starts 60 minutes before departure
                if minutes_to_departure <= 60:
                    # Try to assign a gate
                    gate = self._find_gate(state, flight.terminal)
                    if gate:
                        flight.gate = gate
                        flight.status = "boarding"
                        flight.boarded_at = sim_time
                        state.gate_occupancy[gate] = flight.id
                        # Landing fee (revenue + cost)
                        seats = SEAT_MAP.get(flight.aircraft_type, 180)
                        mtow_tonnes = seats * 0.4  # rough estimate
                        fee = mtow_tonnes * LANDING_FEE_PER_TONNE_EUR
                        state.revenues["landing_fees"] += fee
                        state.costs["landing_fees"] += fee * 0.3  # airport cost p + extra_lanesortion
                    else:
                        # No gate available — gate conflict
                        state.gate_conflicts += 1
                        # Add delay
                        flight.delay_minutes += 1
                        flight.estimated_departure = sched + timedelta(minutes=1)
                        state.total_delay_minutes += 1

                # Security queue modelling (simplified)
                if minutes_to_departure <= 90 and minutes_to_departure > 60:
                    terminal = flight.terminal or "A"
                    sec_lanes = infra.security_lanes_per_terminal.get(terminal, 4) + extra_lanes
                    pax_per_min = flight.pax_count / 30  # pax arrive over 30 min
                    throughput_per_min = sec_lanes * 3  # ~3 pax/min/lane
                    if pax_per_min > throughput_per_min:
                        queue_build = pax_per_min - throughput_per_min
                        state.security_queues[terminal] = (
                            state.security_queues.get(terminal, 0) + int(queue_build)
                        )
                        wait = state.security_queues[terminal] / max(1, throughput_per_min)
                        if wait > state.security_wait_max:
                            state.security_wait_max = wait
                        state.peak_security_queue[terminal] = max(
                            state.peak_security_queue.get(terminal, 0),
                            state.security_queues.get(terminal, 0),
                        )

            elif flight.status == "boarding":
                if minutes_to_departure <= 0:
                    # Check runway capacity
                    if state.runway_departures_this_hour < max_dep:
                        flight.status = "departed"
                        flight.departed_at = sim_time
                        state.runway_departures_this_hour += 1

                        # Free gate
                        if flight.gate and state.gate_occupancy.get(flight.gate) == flight.id:
                            state.gate_occupancy[flight.gate] = None
                            # Gate utilisation tracking
                            board_duration_hr = (
                                (sim_time - flight.boarded_at).total_seconds() / 3600
                                if flight.boarded_at else 1.0
                            )
                            state.gate_hours_used += board_duration_hr
                            state.costs["gate_fees"] += board_duration_hr * GATE_FEE_PER_HOUR_EUR
                            state.revenues["gate_fees"] += board_duration_hr * GATE_FEE_PER_HOUR_EUR

                        # Calculate final delay
                        actual_delay = (sim_time - flight.scheduled_departure).total_seconds() / 60
                        if actual_delay > 0:
                            flight.delay_minutes = int(actual_delay)
                            state.total_delay_minutes += actual_delay
                            state.max_delay_minutes = max(state.max_delay_minutes, actual_delay)

                            # Delay costs
                            state.costs["delay"] += actual_delay * DELAY_COST_PER_MINUTE_EUR

                            # EU261 liability
                            eu261 = self._compute_eu261(actual_delay, flight.distance_km, flight.pax_count)
                            state.costs["eu261"] += eu261

                    else:
                        # Holding — runway at capacity
                        state.holding_events += 1
                        flight.delay_minutes += 1 + extra_lanes
                        flight.estimated_departure = sim_time + timedelta(minutes=1)
                        state.total_delay_minutes += 1

            elif flight.status == "departed":
                # Flight completes after flying time (simplified)
                fly_time_min = max(30, flight.distance_km / 14)  # ~840 km/h
                if flight.departed_at and (sim_time - flight.departed_at).total_seconds() / 60 >= fly_time_min:
                    flight.status = "completed"

        # Decay security queues naturally each minute
        for terminal in list(state.security_queues.keys()):
            sec_lanes = infra.security_lanes_per_terminal.get(terminal, 4) + extra_lanes
            drain = sec_lanes * 3  # 3 pax/min/lane
            state.security_queues[terminal] = max(0, state.security_queues[terminal] - drain)

        # Baggage throughput tracking
        active_pax = sum(
            f.pax_count for f in state.flights.values()
            if f.status in ("boarding", "departed")
        )
        bags_per_min = active_pax * 1.3 / 60  # 1.3 bags/pax on average
        if bags_per_min > infra.sorting_capacity_per_hour / 60:
            state.baggage_throughput = max(state.baggage_throughput, int(bags_per_min * 60))

    def _find_gate(self, state: PlanningSimState, terminal: str | None) -> str | None:
        """Find an available gate, preferring the assigned terminal."""
        # First try the preferred terminal
        for gate_id, occupant in state.gate_occupancy.items():
            if occupant is None and gate_id.startswith(terminal or ""):
                return gate_id
        # Fallback to any terminal
        for gate_id, occupant in state.gate_occupancy.items():
            if occupant is None:
                return gate_id
        return None

    @staticmethod
    def _compute_eu261(delay_minutes: float, distance_km: float, pax_count: int) -> float:
        """Compute EU261 compensation liability for a delayed flight."""
        compensation = 0.0
        for min_delay, max_dist, amount in EU261_TIERS:
            if delay_minutes >= min_delay and distance_km <= max_dist:
                compensation = amount
                break
        if compensation > 0:
            # Assume ~30% of pax claim
            claiming_pax = int(pax_count * 0.30)
            return claiming_pax * compensation
        return 0.0

    def _build_result(
        self,
        state: PlanningSimState,
        sim_date: date,
        infra: InfrastructureConfig,
        elapsed: float,
    ) -> DayResult:
        """Extract KPIs from final simulation state."""
        total = len(state.flights)
        departed = [f for f in state.flights.values() if f.status in ("completed", "departed")]
        delayed = [f for f in departed if f.delay_minutes > 15]
        on_time = [f for f in departed if f.delay_minutes <= 15]

        avg_delay = (
            sum(f.delay_minutes for f in departed) / max(1, len(departed))
            if departed else 0.0
        )

        # Utilisation calculations
        gate_util = (state.gate_hours_used / max(1.0, state.gate_hours_available)) * 100
        peak_runway_ops = max(state.runway_ops_per_hour) if state.runway_ops_per_hour else 0
        max_runway_cap = RUNWAY_CAPACITY["CAVOK"]["departure"] + RUNWAY_CAPACITY["CAVOK"]["arrival"]
        runway_util = (peak_runway_ops / max(1, max_runway_cap)) * 100

        # Security utilisation
        total_sec_lanes = infra.total_security_lanes
        max_sec_queue = max(state.peak_security_queue.values()) if state.peak_security_queue else 0
        sec_util = (max_sec_queue / max(1, total_sec_lanes * 20)) * 100  # 20 pax queue per lane = 100%

        # Baggage utilisation
        bag_util = (state.baggage_throughput / max(1, infra.sorting_capacity_per_hour)) * 100

        total_cost = sum(state.costs.values())
        total_revenue = sum(state.revenues.values())

        return DayResult(
            sim_date=sim_date,
            infrastructure_label="baseline",
            total_flights=total,
            flights_on_time=len(on_time),
            flights_delayed=len(delayed),
            flights_cancelled=0,
            avg_delay_minutes=avg_delay,
            max_cascade_depth=state.max_cascade_depth,
            missed_connections=state.missed_connections,
            gate_conflicts=state.gate_conflicts,
            holding_events=state.holding_events,
            security_wait_max_minutes=state.security_wait_max,
            runway_utilisation_pct=min(100.0, runway_util),
            gate_utilisation_pct=min(100.0, gate_util),
            security_utilisation_pct=min(100.0, sec_util),
            baggage_utilisation_pct=min(100.0, bag_util),
            total_cost_eur=total_cost,
            total_revenue_eur=total_revenue,
            net_eur=total_revenue - total_cost,
            eu261_liability_eur=state.costs["eu261"],
            incident_cost_eur=state.costs["incident"],
        )

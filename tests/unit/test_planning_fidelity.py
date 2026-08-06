"""Fidelity-bug regression tests for the planning engine (ROADMAP_REAL_LDT.md A2).

Two defects were flagged as "confidently wrong":

1. Runway capacity did not scale with runway count — a no-op branch in
   ``simulation._tick`` meant closing or adding a runway had *zero* effect on
   throughput.
2. ``benefit_extractor`` monetized ``missed_connections`` into the NPV even
   though the simulation never populates it (no connection model), producing a
   fake benefit line in an eight-figure decision.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, time as dt_time
from pathlib import Path

_SERVICES_DIR = Path(__file__).resolve().parents[2] / "services"
sys.path.insert(0, str(_SERVICES_DIR / "planning-service"))
sys.path.insert(0, str(_SERVICES_DIR))

from engine.infrastructure import InfrastructureConfig, RunwayConfig  # noqa: E402
from engine.results import aggregate_kpi  # noqa: E402
from engine.simulation import PlanningSimEngine  # noqa: E402
from finance.benefit_extractor import extract_annual_benefit  # noqa: E402


class _BurstAdapter:
    """A schedule that saturates runway departure capacity in one hour.

    Many flights depart within a single hour so the runway (not the gates)
    becomes the binding constraint — isolating the runway-count effect.
    """

    def __init__(self, n_flights: int = 90):
        self._n = n_flights

    @property
    def source_name(self) -> str:
        return "burst"

    @property
    def is_real_data(self) -> bool:
        return False

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        flights = []
        for i in range(self._n):
            # All depart between 09:00 and 09:59 → concentrated runway demand.
            dep = datetime.combine(sim_date, dt_time(9, i % 60))
            flights.append({
                "flight_number": f"XX{i:04d}",
                "airline_code": "XX",
                "origin_iata": "ART",
                "destination_iata": "JFK",
                "aircraft_type": "A320",
                "scheduled_departure": dep.isoformat(),
                "pax_count": 150,
                "distance_km": 800,
            })
        return flights

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        # CAVOK all day: the category assumes 2 usable runways at full rate,
        # so runway *count* is the only thing that changes capacity here.
        return [
            {"hour": h, "category": "CAVOK", "wind_speed_kt": 5, "visibility_m": 10000}
            for h in range(24)
        ]

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        return 100.0


def _config(n_runways: int) -> InfrastructureConfig:
    """A gate-rich config so runways, not gates, are the bottleneck."""
    runways = [RunwayConfig(f"R{i}", ils=(i == 0)) for i in range(n_runways)]
    return InfrastructureConfig(
        gates_per_terminal={"A": 30, "B": 30, "C": 30},
        runways=runways,
        security_lanes_per_terminal={"A": 12, "B": 12, "C": 12},
    )


class TestRunwayCapacityScaling:

    def test_fewer_runways_reduce_throughput(self):
        """Closing a runway (2→1) in good weather must increase delay.

        Before the fix this branch was a no-op, so one and two runways produced
        identical throughput and this assertion would fail (delays equal).
        """
        engine = PlanningSimEngine(adapter=_BurstAdapter(90), seed=42)

        r_two = engine.run_day(date(2026, 6, 15), _config(2), seed=42)
        r_one = engine.run_day(date(2026, 6, 15), _config(1), seed=42)

        assert r_one.avg_delay_minutes > r_two.avg_delay_minutes, (
            f"one-runway delay {r_one.avg_delay_minutes} should exceed "
            f"two-runway delay {r_two.avg_delay_minutes}"
        )

    def test_capacity_is_monotonic_in_runways(self):
        """More runways never produce worse average delay under a fixed schedule."""
        engine = PlanningSimEngine(adapter=_BurstAdapter(90), seed=7)
        delays = [
            engine.run_day(date(2026, 6, 15), _config(n), seed=7).avg_delay_minutes
            for n in (1, 2, 3)
        ]
        assert delays[0] >= delays[1] >= delays[2]


class TestBenefitExtractorHonesty:

    def test_missed_connections_not_monetized(self):
        """A missed_connections delta must not move the total benefit."""
        baseline = {
            "eu261_liability_eur": aggregate_kpi([0.0]),
            "avg_delay_minutes": aggregate_kpi([0.0]),
            "total_revenue_eur": aggregate_kpi([0.0]),
            "total_flights": aggregate_kpi([420.0]),
            "missed_connections": aggregate_kpi([100.0]),  # large fake signal
        }
        scenario = dict(baseline)
        scenario["missed_connections"] = aggregate_kpi([0.0])  # "improved" by 100/day

        breakdown = extract_annual_benefit(baseline, scenario)

        # The always-zero, unmodeled metric contributes nothing.
        assert breakdown.missed_connections_avoided_annual == 0.0
        # And it is excluded from the headline NPV input.
        assert breakdown.total_annual_benefit == 0.0

    def test_real_benefits_still_counted(self):
        """EU261 + delay + revenue improvements still flow into the total."""
        baseline = {
            "eu261_liability_eur": aggregate_kpi([10_000.0]),
            "avg_delay_minutes": aggregate_kpi([20.0]),
            "total_revenue_eur": aggregate_kpi([0.0]),
            "total_flights": aggregate_kpi([420.0]),
            "missed_connections": aggregate_kpi([50.0]),
        }
        scenario = {
            "eu261_liability_eur": aggregate_kpi([4_000.0]),   # saved 6000/day
            "avg_delay_minutes": aggregate_kpi([10.0]),         # saved 10 min/flight
            "total_revenue_eur": aggregate_kpi([5_000.0]),      # +5000/day
            "total_flights": aggregate_kpi([420.0]),
            "missed_connections": aggregate_kpi([0.0]),         # ignored
        }

        breakdown = extract_annual_benefit(baseline, scenario)

        assert breakdown.eu261_avoided_annual > 0
        assert breakdown.delay_cost_avoided_annual > 0
        assert breakdown.revenue_uplift_annual > 0
        assert breakdown.missed_connections_avoided_annual == 0.0
        expected = (
            breakdown.eu261_avoided_annual
            + breakdown.delay_cost_avoided_annual
            + breakdown.revenue_uplift_annual
        )
        assert breakdown.total_annual_benefit == expected

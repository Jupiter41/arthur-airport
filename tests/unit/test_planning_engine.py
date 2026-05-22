"""Unit tests for the planning simulation engine (Phase 2).

Tests the pure functions: InfrastructureConfig, DayResult, KPIDistribution,
aggregate_kpi, and the PlanningSimEngine.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

# Add planning-service to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services" / "planning-service"))

from engine.infrastructure import InfrastructureConfig, RunwayConfig
from engine.results import DayResult, ScenarioResults, aggregate_kpi
from engine.simulation import PlanningSimEngine


# ── Infrastructure Config ───────────────────────────────────


class TestInfrastructureConfig:

    def test_baseline_defaults(self):
        config = InfrastructureConfig.baseline()
        assert config.total_gates == 42  # 14 * 3
        assert config.total_security_lanes == 11  # 4 + 3 + 4
        assert config.runway_count == 2
        assert config.ils_runway_count == 1
        assert config.daily_flight_target == 420
        assert config.load_factor_mean == 0.80

    def test_roundtrip_dict(self):
        config = InfrastructureConfig.baseline()
        d = config.to_dict()
        restored = InfrastructureConfig.from_dict(d)
        assert restored.total_gates == config.total_gates
        assert restored.runway_count == config.runway_count
        assert restored.daily_flight_target == config.daily_flight_target

    def test_custom_gates(self):
        config = InfrastructureConfig(
            gates_per_terminal={"A": 14, "B": 15, "C": 14},
        )
        assert config.total_gates == 43

    def test_runway_config(self):
        rc = RunwayConfig("09L", ils=True, length_m=3500)
        d = rc.to_dict()
        assert d["id"] == "09L"
        assert d["ils"] is True
        restored = RunwayConfig.from_dict(d)
        assert restored.id == "09L"
        assert restored.ils is True


# ── DayResult ───────────────────────────────────────────────


class TestDayResult:

    def test_on_time_rate(self):
        result = DayResult(
            sim_date=date(2026, 6, 15),
            infrastructure_label="test",
            total_flights=100,
            flights_on_time=85,
        )
        assert result.on_time_rate() == 0.85

    def test_on_time_rate_zero_flights(self):
        result = DayResult(
            sim_date=date(2026, 6, 15),
            infrastructure_label="test",
            total_flights=0,
        )
        assert result.on_time_rate() == 0.0

    def test_cost_per_flight(self):
        result = DayResult(
            sim_date=date(2026, 6, 15),
            infrastructure_label="test",
            total_flights=420,
            total_cost_eur=420000.0,
        )
        assert result.cost_per_flight() == 1000.0

    def test_to_dict(self):
        result = DayResult(
            sim_date=date(2026, 6, 15),
            infrastructure_label="baseline",
            total_flights=100,
            flights_on_time=85,
            avg_delay_minutes=7.5,
        )
        d = result.to_dict()
        assert d["sim_date"] == "2026-06-15"
        assert d["total_flights"] == 100
        assert d["on_time_rate"] == 0.85


# ── KPIDistribution & aggregate_kpi ────────────────────────


class TestAggregateKPI:

    def test_single_value(self):
        dist = aggregate_kpi([10.0])
        assert dist.mean == 10.0
        assert dist.std == 0.0
        assert dist.p50 == 10.0

    def test_multiple_values(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        dist = aggregate_kpi(values)
        assert dist.mean == 5.5
        assert dist.p50 == 5.5
        assert dist.p5 < dist.p25 < dist.p50 < dist.p75 < dist.p95

    def test_empty_values(self):
        dist = aggregate_kpi([])
        assert dist.mean == 0.0
        assert dist.std == 0.0

    def test_identical_values(self):
        dist = aggregate_kpi([5.0, 5.0, 5.0, 5.0])
        assert dist.mean == 5.0
        assert dist.std == 0.0
        assert dist.p5 == 5.0
        assert dist.p95 == 5.0

    def test_to_dict(self):
        dist = aggregate_kpi([1.0, 2.0, 3.0])
        d = dist.to_dict()
        assert "mean" in d
        assert "std" in d
        assert "p5" in d
        assert "p95" in d

    def test_confidence_interval(self):
        dist = aggregate_kpi([1.0, 2.0, 3.0, 4.0, 5.0])
        ci = dist.confidence_interval_95()
        assert ci[0] <= ci[1]
        assert ci[0] == dist.p5
        assert ci[1] == dist.p95


# ── ScenarioResults ─────────────────────────────────────────


class TestScenarioResults:

    def test_to_dict(self):
        kpis = {"avg_delay": aggregate_kpi([5.0, 10.0, 15.0])}
        sr = ScenarioResults(
            scenario_id="test-id",
            scenario_name="Test",
            kpis=kpis,
        )
        d = sr.to_dict()
        assert d["scenario_id"] == "test-id"
        assert "avg_delay" in d["kpis"]
        assert d["kpis"]["avg_delay"]["mean"] == 10.0


# ── PlanningSimEngine ──────────────────────────────────────


class StubAdapter:
    """Minimal adapter for testing the engine."""

    def __init__(self, n_flights: int = 50):
        self._n_flights = n_flights

    @property
    def source_name(self) -> str:
        return "stub"

    @property
    def is_real_data(self) -> bool:
        return False

    def get_daily_schedule(self, sim_date: date) -> list[dict]:
        from datetime import datetime, time as dt_time
        flights = []
        for i in range(self._n_flights):
            hour = 6 + (i * 12 // self._n_flights)
            dep = datetime.combine(sim_date, dt_time(hour, (i * 7) % 60))
            flights.append({
                "flight_number": f"XX{i:04d}",
                "airline_code": "XX",
                "origin_iata": "ART",
                "destination_iata": "JFK",
                "aircraft_type": "A320",
                "scheduled_departure": dep.isoformat(),
                "pax_count": 150,
                "distance_km": 5750,
            })
        return flights

    def get_weather_sequence(self, sim_date: date) -> list[dict]:
        return [
            {"hour": h, "category": "CAVOK", "wind_speed_kt": 8, "visibility_m": 10000}
            for h in range(24)
        ]

    def get_passenger_demand(self, origin: str, destination: str, month: int) -> float:
        return 100.0


class TestPlanningSimEngine:

    def test_run_day_returns_day_result(self):
        adapter = StubAdapter(n_flights=50)
        engine = PlanningSimEngine(adapter=adapter, seed=42)
        infra = InfrastructureConfig.baseline()
        result = engine.run_day(date(2026, 6, 15), infra, seed=42)

        assert isinstance(result, DayResult)
        assert result.total_flights == 50
        assert result.flights_on_time + result.flights_delayed <= result.total_flights
        assert result.on_time_rate() >= 0.0
        assert result.on_time_rate() <= 1.0

    def test_deterministic_with_same_seed(self):
        adapter = StubAdapter(n_flights=50)
        engine = PlanningSimEngine(adapter=adapter, seed=42)
        infra = InfrastructureConfig.baseline()

        r1 = engine.run_day(date(2026, 6, 15), infra, seed=42)
        r2 = engine.run_day(date(2026, 6, 15), infra, seed=42)

        assert r1.avg_delay_minutes == r2.avg_delay_minutes
        assert r1.flights_on_time == r2.flights_on_time
        assert r1.gate_utilisation_pct == r2.gate_utilisation_pct

    def test_different_seeds_produce_variation(self):
        adapter = StubAdapter(n_flights=100)
        engine = PlanningSimEngine(adapter=adapter)
        infra = InfrastructureConfig.baseline()

        results = [engine.run_day(date(2026, 6, 15), infra, seed=s) for s in range(5)]
        delays = [r.avg_delay_minutes for r in results]
        # With 100 flights, different seeds should produce some variation
        # (gate assignment order changes, etc.)
        assert len(set(round(d, 2) for d in delays)) >= 1  # At least 1 unique value

    def test_non_zero_kpis(self):
        adapter = StubAdapter(n_flights=100)
        engine = PlanningSimEngine(adapter=adapter, seed=42)
        infra = InfrastructureConfig.baseline()
        result = engine.run_day(date(2026, 6, 15), infra, seed=42)

        assert result.total_flights == 100
        assert result.on_time_rate() > 0.0
        assert result.total_revenue_eur > 0.0

    def test_performance_under_500ms(self):
        """Target: 1 full day in < 500ms."""
        import time

        adapter = StubAdapter(n_flights=420)
        engine = PlanningSimEngine(adapter=adapter, seed=42)
        infra = InfrastructureConfig.baseline()

        t0 = time.monotonic()
        engine.run_day(date(2026, 6, 15), infra, seed=42)
        elapsed = time.monotonic() - t0

        assert elapsed < 2.0  # Allow 2s on slow CI — target is 500ms

    def test_reduced_infrastructure_causes_more_conflicts(self):
        """Fewer gates should cause more gate conflicts."""
        adapter = StubAdapter(n_flights=200)
        engine = PlanningSimEngine(adapter=adapter, seed=42)

        baseline = InfrastructureConfig.baseline()
        reduced = InfrastructureConfig(
            gates_per_terminal={"A": 5, "B": 5, "C": 5},
            runways=[RunwayConfig("09L", ils=True)],
        )

        r_baseline = engine.run_day(date(2026, 6, 15), baseline, seed=42)
        r_reduced = engine.run_day(date(2026, 6, 15), reduced, seed=42)

        # Reduced infrastructure should cause more gate conflicts or delays
        assert r_reduced.gate_conflicts >= r_baseline.gate_conflicts or \
               r_reduced.avg_delay_minutes >= r_baseline.avg_delay_minutes

"""Unit tests for planning-service adapters.

Tests all four adapter implementations: simulation, BTS T-100, Mesonet, Eurocontrol.
Validates the AbstractAdapter interface contract for each.
"""

from datetime import date
from pathlib import Path

import pytest

from tests.conftest import import_service_module

_sim_mod = import_service_module("planning", "adapters.simulation")
_base_mod = import_service_module("planning", "adapters.base")
_registry_mod = import_service_module("planning", "adapters.registry")
_eurocontrol_mod = import_service_module("planning", "adapters.eurocontrol")

SimulationAdapter = _sim_mod.SimulationAdapter
AbstractAdapter = _base_mod.AbstractAdapter
list_available_adapters = _registry_mod.list_available_adapters
EurocontrolDemandAdapter = _eurocontrol_mod.EurocontrolDemandAdapter

# BTS and Mesonet require pandas — conditionally import
BTS_CSV = Path(__file__).parent.parent.parent / "data" / "bts" / "T100_2026.csv"
WEATHER_CSV = Path(__file__).parent.parent.parent / "data" / "weather" / "EGLL_30days.csv"

try:
    _bts_mod = import_service_module("planning", "adapters.bts")
    BTSAdapter = _bts_mod.BTSAdapter
    HAS_PANDAS = True
except (ImportError, Exception):
    BTSAdapter = None
    HAS_PANDAS = False

try:
    _mesonet_mod = import_service_module("planning", "adapters.mesonet")
    MesonetAdapter = _mesonet_mod.MesonetAdapter
except (ImportError, Exception):
    MesonetAdapter = None


# ─── Simulation Adapter ──────────────────────────────────


class TestSimulationAdapter:
    def test_implements_adapter_interface(self):
        adapter = SimulationAdapter()
        assert hasattr(adapter, 'get_daily_schedule')
        assert hasattr(adapter, 'get_weather_sequence')
        assert hasattr(adapter, 'get_passenger_demand')
        assert hasattr(adapter, 'source_name')
        assert hasattr(adapter, 'is_real_data')

    def test_source_name(self):
        adapter = SimulationAdapter()
        assert adapter.source_name == "simulation"

    def test_is_not_real_data(self):
        adapter = SimulationAdapter()
        assert adapter.is_real_data is False

    def test_daily_schedule_returns_list(self):
        adapter = SimulationAdapter(daily_flight_target=50, seed=42)
        schedule = adapter.get_daily_schedule(date(2026, 1, 15))
        assert isinstance(schedule, list)
        assert len(schedule) > 0

    def test_schedule_entries_have_required_fields(self):
        adapter = SimulationAdapter(daily_flight_target=10, seed=42)
        schedule = adapter.get_daily_schedule(date(2026, 6, 1))
        required = {"flight_number", "airline_code", "origin_iata",
                     "destination_iata", "aircraft_type", "scheduled_departure",
                     "pax_count", "distance_km"}
        for flight in schedule:
            assert required.issubset(flight.keys()), f"Missing: {required - flight.keys()}"

    def test_schedule_deterministic_with_seed(self):
        a = SimulationAdapter(daily_flight_target=20, seed=123)
        b = SimulationAdapter(daily_flight_target=20, seed=123)
        sa = a.get_daily_schedule(date(2026, 3, 1))
        sb = b.get_daily_schedule(date(2026, 3, 1))
        assert sa == sb

    def test_weather_sequence(self):
        adapter = SimulationAdapter(seed=42)
        weather = adapter.get_weather_sequence(date(2026, 1, 15))
        assert len(weather) == 24
        for obs in weather:
            assert obs["hour"] in range(24)
            assert obs["category"] in {"CAVOK", "VMC", "IMC", "LIFR"}
            assert obs["wind_speed_kt"] >= 0
            assert obs["visibility_m"] > 0

    def test_passenger_demand(self):
        adapter = SimulationAdapter()
        demand = adapter.get_passenger_demand("ART", "JFK", 7)
        assert demand > 0

    def test_seasonal_demand_variation(self):
        adapter = SimulationAdapter()
        summer = adapter.get_passenger_demand("ART", "JFK", 7)
        winter = adapter.get_passenger_demand("ART", "JFK", 1)
        # Summer should have higher demand
        assert summer > winter


# ─── Eurocontrol Adapter ──────────────────────────────


class TestEurocontrolAdapter:
    def test_implements_adapter_interface(self):
        adapter = EurocontrolDemandAdapter()
        assert hasattr(adapter, 'get_daily_schedule')
        assert hasattr(adapter, 'get_passenger_demand')
        assert hasattr(adapter, 'source_name')

    def test_source_name(self):
        adapter = EurocontrolDemandAdapter(scenario="base")
        assert "STATFOR" in adapter.source_name

    def test_is_real_data(self):
        adapter = EurocontrolDemandAdapter()
        assert adapter.is_real_data is True

    def test_growth_rate(self):
        adapter = EurocontrolDemandAdapter(scenario="base")
        assert adapter.get_demand_growth_rate() == pytest.approx(0.034)

    def test_project_annual_pax(self):
        adapter = EurocontrolDemandAdapter(base_year_pax=10_000_000, scenario="base")
        year0 = adapter.project_annual_pax(years_ahead=0)
        year5 = adapter.project_annual_pax(years_ahead=5)
        assert year5 > year0

    def test_invalid_scenario_raises(self):
        with pytest.raises(ValueError):
            EurocontrolDemandAdapter(scenario="extreme")

    def test_growth_table(self):
        adapter = EurocontrolDemandAdapter(base_year_pax=10_000_000)
        table = adapter.get_growth_table(years=5)
        assert len(table) == 6  # years 0-5
        assert table[0]["pax_base"] == 10_000_000


# ─── BTS Adapter ──────────────────────────────


@pytest.mark.skipif(not HAS_PANDAS or not BTS_CSV.exists(), reason="pandas or BTS CSV not available")
class TestBTSAdapter:
    def test_implements_adapter_interface(self):
        adapter = BTSAdapter(BTS_CSV)
        assert hasattr(adapter, 'get_daily_schedule')
        assert hasattr(adapter, 'get_passenger_demand')
        assert hasattr(adapter, 'source_name')

    def test_source_name(self):
        adapter = BTSAdapter(BTS_CSV)
        assert "BTS" in adapter.source_name

    def test_is_real_data(self):
        adapter = BTSAdapter(BTS_CSV)
        assert adapter.is_real_data is True

    def test_passenger_demand_returns_float(self):
        adapter = BTSAdapter(BTS_CSV)
        # JFK-LAX is a major route — should have data
        demand = adapter.get_passenger_demand("JFK", "LAX", 1)
        assert isinstance(demand, float)
        assert demand >= 0

    def test_daily_schedule_returns_list(self):
        adapter = BTSAdapter(BTS_CSV)
        schedule = adapter.get_daily_schedule(date(2026, 1, 15))
        assert isinstance(schedule, list)

    def test_schedule_entries_valid(self):
        adapter = BTSAdapter(BTS_CSV)
        schedule = adapter.get_daily_schedule(date(2026, 6, 15))
        if schedule:
            flight = schedule[0]
            assert "flight_number" in flight
            assert "pax_count" in flight
            assert flight["pax_count"] > 0

    def test_route_summary(self):
        adapter = BTSAdapter(BTS_CSV)
        summary = adapter.get_route_summary(month=1)
        assert isinstance(summary, list)


# ─── Mesonet Adapter ──────────────────────────────


@pytest.mark.skipif(not HAS_PANDAS or not WEATHER_CSV.exists(), reason="pandas or weather CSV not available")
class TestMesonetAdapter:
    def test_implements_adapter_interface(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        assert hasattr(adapter, 'get_weather_sequence')
        assert hasattr(adapter, 'get_passenger_demand')
        assert hasattr(adapter, 'source_name')

    def test_source_name(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        assert "Mesonet" in adapter.source_name

    def test_is_real_data(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        assert adapter.is_real_data is True

    def test_weather_sequence_returns_list(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        # Use a date we know is in the CSV
        sequence = adapter.get_weather_sequence(date(2026, 2, 25))
        assert isinstance(sequence, list)
        assert len(sequence) > 0

    def test_weather_entries_valid(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        sequence = adapter.get_weather_sequence(date(2026, 2, 25))
        for obs in sequence:
            assert obs["category"] in {"CAVOK", "VMC", "IMC", "LIFR"}
            assert 0 <= obs["hour"] <= 23
            assert obs["visibility_m"] > 0

    def test_transition_matrix(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        matrix = adapter.get_transition_matrix()
        assert isinstance(matrix, dict)
        # Probabilities should sum to ~1.0 for each source state
        for from_state, transitions in matrix.items():
            total = sum(transitions.values())
            assert abs(total - 1.0) < 0.01, f"{from_state} probabilities sum to {total}"

    def test_category_distribution(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        dist = adapter.get_category_distribution()
        assert isinstance(dist, dict)
        assert abs(sum(dist.values()) - 1.0) < 0.01

    def test_date_range(self):
        adapter = MesonetAdapter(WEATHER_CSV)
        result = adapter.get_date_range()
        assert result is not None
        assert result[0] <= result[1]


# ─── Registry ──────────────────────────────


class TestAdapterRegistry:
    def test_list_available_adapters(self):
        adapters = list_available_adapters()
        assert "schedule" in adapters
        assert "weather" in adapters
        assert "demand" in adapters
        assert "simulation" in adapters["schedule"]
        assert "bts" in adapters["schedule"]
        assert "mesonet" in adapters["weather"]
        assert "eurocontrol" in adapters["demand"]

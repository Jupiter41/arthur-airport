"""Exercise actual producer payloads, aggregate facts and graph recovery."""

import asyncio
import importlib
import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 1, 1, 10)


def test_actual_weather_payload_changes_category_and_capacity(monkeypatch):
    state = import_service_module("analysis", "services.state").OperationalState()
    producer = import_service_module("weather", "kafka.producer")
    emitted = []
    monkeypatch.setattr(producer, "produce_event", lambda **kw: emitted.append(kw))
    producer.emit_weather_state_changed(
        NOW, "synthetic-weather", "CAVOK", "LIFR",
        {"visibility_m": 400, "wind_direction": 90, "wind_speed_kt": 5,
         "wind_gust_kt": 8, "ceiling_ft": 100, "temperature_c": 5, "phenomena": ["FG"]},
        {"runway_impact": "single_runway", "arrival_rate": 8, "departure_rate": 6},
    )
    state.on_weather_state_changed(emitted[0]["payload"])
    assert state.weather.category == "LIFR"
    assert state.weather.runway_capacity_pct == pytest.approx(14 / 64 * 100)


def test_baggage_snapshot_is_not_suppressed_in_bulk_and_is_replay_safe(monkeypatch):
    state = import_service_module("analysis", "services.state").OperationalState()
    producer = import_service_module("baggage", "kafka.producer")
    conveyor = importlib.import_module("services.conveyor")
    system = conveyor.ConveyorSystem()
    zone = system.get_zone("make-up-B-1")
    zone.queue.extend([MagicMock() for _ in range(15)])
    emitted = []
    monkeypatch.setattr(producer, "_produce_event", lambda kind, clock, payload, **kw: emitted.append((kind, payload)))
    producer.set_bulk_mode(True)
    snapshot = {"zones": system.get_zone_summary(), "at": NOW.isoformat()}
    producer.emit_zone_snapshot(snapshot, NOW)
    assert emitted[0][0] == "BaggageZoneSnapshot"
    for _ in range(2):
        state.on_baggage_zone_snapshot(emitted[0][1])
    assert state.baggage_zones["make-up-B-1"].current_count == 15
    assert state.get_makeup_utilisation_by_terminal()["Terminal B"] > 0
    state.on_baggage_zone_snapshot({"zones": [], "at": "2026-01-01T09:00:00"})
    assert state.baggage_zones["make-up-B-1"].current_count == 15
    state.on_baggage_status_changed({"scan_zone": "make-up-B-1", "new_status": "loaded"})
    assert state.baggage_zones["make-up-B-1"].current_count == 15


def test_graph_recovery_restores_operational_entities_without_inventing_clock():
    module = import_service_module("analysis", "services.state")
    state = module.OperationalState()
    snapshot = {
        "flights": [{"flight": {"id": "f1", "direction": "arrival", "status": "at_gate",
                                 "pax_count": 120, "scheduled_time": NOW.isoformat()},
                     "gate_id": "B01", "terminal_id": "T-B"}],
        "gates": [{"gate": {"id": gate, "terminal_id": "T-B", "status": "available"}}
                  for gate in ["B01", "B02"]],
        "incidents": [{"incident": {"id": "i1", "status": "active", "type": "system_failure"}}],
        "weather": [{"weather": {"category": "LIFR", "recommended_arrival_rate": 8,
                                 "recommended_departure_rate": 6, "timestamp": NOW.isoformat()}}],
        "baggage": [{"document": json.dumps({"zones": [], "at": NOW.isoformat()})}],
    }
    state.restore_graph(snapshot)
    assert state.sim_time is None
    assert state.flights["f1"].flight_type == "arrival"
    assert state.flights["f1"].passenger_count == 120
    assert state.flights["f1"].scheduled_arrival == NOW
    assert state.get_free_gates_by_terminal() == {"Terminal B": 1}
    assert "i1" in state.active_incidents
    assert state.weather.category == "LIFR"
    snapshot["flights"] = []
    snapshot["incidents"] = []
    state.restore_graph(snapshot)
    assert state.flights == {} and state.active_incidents == {}
    assert state.get_free_gates_by_terminal() == {"Terminal B": 2}


def test_what_if_requires_sim_clock_and_preserves_live_state():
    state_module = import_service_module("analysis", "services.state")
    whatif = importlib.import_module("services.whatif")
    domain = importlib.import_module("models.domain")
    state = state_module.OperationalState()
    request = domain.WhatIfRequest(actions=[domain.WhatIfAction(
        action_type="open_security_lane", parameters={"terminal": "Terminal B", "new_lane_count": 5},
    )])
    with pytest.raises(ValueError, match="Simulation clock"):
        whatif.run_what_if(state, request)
    state.sim_time = NOW
    state.security["Terminal B"].queue_depth = 100
    result = whatif.run_what_if(state, request)
    assert result.sim_time_at_request == NOW
    assert state.security["Terminal B"].queue_depth == 100
    assert state.security["Terminal B"].open_lanes == 4


def test_graph_loader_reads_all_sections_from_one_driver_transaction(monkeypatch):
    module = import_service_module("analysis", "db.neo4j")
    queries = []

    class Tx:
        async def run(self, query):
            queries.append(query)
            class Result:
                async def data(self):
                    return []
            return Result()

    class Session:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def execute_read(self, read):
            return await read(Tx())

    monkeypatch.setattr(module, "get_driver", lambda: MagicMock(session=Session))
    snapshot = asyncio.run(module.load_operational_projection())
    assert set(snapshot) == {"flights", "gates", "incidents", "weather", "baggage"}
    assert len(queries) == 5
    assert all("SET " not in query and "CREATE " not in query for query in queries)

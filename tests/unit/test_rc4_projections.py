"""RC4: decisions come from consumed events, not another owner's live nodes."""
import asyncio
import importlib
import sys
from datetime import datetime, timedelta
from types import ModuleType
from unittest.mock import MagicMock

import pytest

from tests.conftest import import_service_module

NOW = datetime(2024, 7, 8, 12, 0, 0)


def _view_module():
    import_service_module("flight", "application.commands")
    return importlib.import_module("_common.flight_view")


def _fresh_view(fv, rows=(), gates=({"id": "B07", "terminal_id": "T-B"},), stamp=None):
    fv.VIEW.load(list(rows), list(gates), stamp)
    return fv.VIEW


# ── FlightView ────────────────────────────────────────────────────

def test_view_follows_consumed_facts_in_order():
    fv = _view_module()
    view = _fresh_view(fv)
    view.apply("FlightsScheduled", {"flights": [{
        "id": "F1", "flight_number": "AX1", "direction": "departure", "status": "scheduled",
        "scheduled_time": "2024-07-08T13:00:00", "estimated_time": "2024-07-08T13:00:00"}]},
        "2024-07-07T23:30:00")
    view.apply("FlightGateAssigned", {"flight_id": "F1", "new_gate_id": "B07"}, "2024-07-08T11:55:00")
    view.apply("FlightStatusChanged", {"flight_id": "F1", "new_status": "boarding",
                                       "estimated_time": "2024-07-08T13:10:00Z"}, "2024-07-08T12:20:00")
    flight = view.get("F1")
    assert flight["status"] == "boarding" and flight["gate_id"] == "B07"
    assert flight["terminal_id"] == "T-B"
    assert flight["estimated_time"] == "2024-07-08T13:10:00"     # normalised naive ISO
    view.apply("FlightCTOTAssigned", {"flight_id": "F1", "estimated_time": "2024-07-08T13:30:00",
                                      "delay_minutes": 30}, "2024-07-08T12:40:00")
    assert view.get("F1")["estimated_time"] == "2024-07-08T13:30:00"
    view.apply("FlightCancelled", {"flight_id": "F1"}, "2024-07-08T12:50:00")
    assert view.get("F1")["status"] == "cancelled"


def test_view_ignores_facts_already_in_the_bootstrap_and_older_than_the_last_change():
    fv = _view_module()
    view = _fresh_view(fv, rows=[{"id": "F1", "status": "departed", "direction": "departure"}],
                       stamp=datetime(2024, 7, 8, 12, 0))
    # A replayed fact from before our own checkpoint is already in the snapshot.
    assert not view.apply("FlightStatusChanged", {"flight_id": "F1", "new_status": "boarding"},
                          "2024-07-08T11:58:00")
    assert view.get("F1")["status"] == "departed"
    assert view.apply("FlightStatusChanged", {"flight_id": "F1", "new_status": "airborne"},
                      "2024-07-08T12:05:00")
    assert not view.apply("FlightStatusChanged", {"flight_id": "F1", "new_status": "departed"},
                          "2024-07-08T12:01:00")
    assert view.get("F1")["status"] == "airborne"


def test_view_select_and_evict():
    fv = _view_module()
    view = _fresh_view(fv, rows=[
        {"id": "D1", "direction": "departure", "status": "boarding", "scheduled_time": "2024-07-08T12:30:00"},
        {"id": "D2", "direction": "departure", "status": "scheduled", "scheduled_time": "2024-07-08T15:00:00"},
        {"id": "A1", "direction": "arrival", "status": "arrived", "scheduled_time": "2024-07-06T08:00:00",
         "actual_time": "2024-07-06T08:10:00"},
    ])
    assert [f["id"] for f in view.select(statuses=["boarding"], direction="departure")] == ["D1"]
    assert [f["id"] for f in view.select(direction="departure", scheduled_before="2024-07-08T13:00:00")] == ["D1"]
    assert view.evict(NOW) == 1 and view.get("A1") is None


def test_late_seed_not_in_snapshot_is_not_discarded_by_global_stamp():
    fv = _view_module()
    view = _fresh_view(fv, rows=[{"id": "existing", "status": "arrived"}], stamp=NOW)
    assert view.apply("FlightsScheduled", {"flights": [
        {"id": "late", "direction": "arrival", "status": "scheduled"},
    ]}, NOW - timedelta(hours=12))
    assert view.apply("FlightStatusChanged", {"flight_id": "late", "new_status": "at_gate"},
                      NOW - timedelta(hours=1))
    assert view.get("late")["status"] == "at_gate"
    assert not view.apply("FlightStatusChanged", {"flight_id": "existing", "new_status": "scheduled"},
                          NOW - timedelta(hours=1))


def test_unknown_events_are_not_flight_facts():
    fv = _view_module()
    view = _fresh_view(fv)
    assert not view.apply("PassengerStatusChanged", {"flight_id": "F1"}, "2024-07-08T12:00:00")
    assert view.get("F1") is None


# ── flight-service: BoardingProgress gates departure ──────────────

def _flight_consumer(monkeypatch):
    import_service_module("flight", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    return importlib.import_module("kafka.consumer")


def test_flight_keeps_the_newest_boarding_progress(monkeypatch):
    consumer = _flight_consumer(monkeypatch)
    monkeypatch.setattr(consumer._state, "boarding_progress", {})
    consumer._on_boarding_progress({"flights": [{"flight_id": "F1", "boarded": 50, "total": 100}]},
                                   datetime(2024, 7, 8, 12, 1))
    consumer._on_boarding_progress({"flights": [{"flight_id": "F1", "boarded": 10, "total": 100}]},
                                   datetime(2024, 7, 8, 12, 0))   # older: ignored
    assert consumer.boarded_fraction(consumer._state.boarding_progress, "F1") == 0.5
    assert consumer.boarded_fraction(consumer._state.boarding_progress, "unknown") == 0.0
    consumer._on_boarding_progress({"flights": [{"flight_id": "F2", "boarded": 0, "total": 0}]},
                                   datetime(2024, 7, 8, 12, 2))
    assert consumer.boarded_fraction(consumer._state.boarding_progress, "F2") == 1.0
    assert not hasattr(importlib.import_module("db.neo4j"), "get_boarded_percentage")


def test_flight_drops_other_passenger_facts_unparsed(monkeypatch):
    consumer = _flight_consumer(monkeypatch)
    called = []
    monkeypatch.setattr(consumer, "_validate_envelope", lambda env: called.append(env) or (None, {}, None))
    asyncio.run(consumer._dispatch({"producer": "passenger-service", "event_type": "PassengerStatusChanged"}))
    assert called == []
    assert "passengers.events" in consumer._TOPICS


def test_flight_status_facts_carry_the_record_fields(monkeypatch):
    consumer = _flight_consumer(monkeypatch)
    fields = consumer._record_fields({"scheduled_time": "2024-07-08T13:00:00",
                                      "estimated_time": "2024-07-08T13:00:00", "pax_count": 160},
                                     estimated_time="2024-07-08T13:20:00")
    assert fields["estimated_time"] == "2024-07-08T13:20:00"
    assert fields["scheduled_time"] == "2024-07-08T13:00:00" and fields["pax_count"] == 160


# ── passenger / baggage reads: identity only ──────────────────────

class _Recorder:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def session(self):
        recorder = self

        class _S:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def run(self, query, **params):
                recorder.calls.append((query, params))
                rows = recorder.rows

                class _R:
                    def __aiter__(self):
                        self._it = iter(rows)
                        return self

                    async def __anext__(self):
                        try:
                            return next(self._it)
                        except StopIteration:
                            raise StopAsyncIteration

                return _R()

        return _S()


def _passenger_db(monkeypatch, rows):
    import_service_module("passenger", "application.commands")
    db = importlib.import_module("db.neo4j")
    recorder = _Recorder(rows)
    monkeypatch.setattr(db, "get_driver", lambda: recorder)
    return db, recorder


def test_passenger_fsm_read_uses_view_ids_and_no_flight_state(monkeypatch):
    fv = _view_module()
    _fresh_view(fv, rows=[
        {"id": "D1", "direction": "departure", "status": "boarding", "scheduled_time": "2024-07-08T12:30:00",
         "estimated_time": "2024-07-08T12:40:00", "gate_id": "B07", "flight_number": "AX1"},
        {"id": "D2", "direction": "departure", "status": "departed", "scheduled_time": "2024-07-08T11:00:00"},
    ])
    db, recorder = _passenger_db(monkeypatch, [{"id": "p1", "flight_id": "D1"}])
    rows = asyncio.run(db.get_passengers_by_status("at_gate", flight_statuses=["boarding"]))
    query, params = recorder.calls[0]
    assert params["fids"] == ["D1"]
    assert "f.status" not in query and "f.estimated_time" not in query and "ASSIGNED_TO" not in query
    assert rows[0]["flight_status"] == "boarding" and rows[0]["terminal_id"] == "T-B"
    assert rows[0]["estimated_time"] == "2024-07-08T12:40:00"
    # No eligible flight in the view: no graph read at all.
    recorder.calls.clear()
    assert asyncio.run(db.get_passengers_by_status("at_gate", flight_statuses=["delayed"])) == []
    assert recorder.calls == []


def test_reconciliation_only_sees_flights_finished_in_the_consumed_stream(monkeypatch):
    fv = _view_module()
    _fresh_view(fv, rows=[
        {"id": "DEP", "direction": "departure", "status": "departed", "scheduled_time": "2024-07-08T11:00:00",
         "actual_time": "2024-07-08T11:05:00"},
        {"id": "ARR", "direction": "arrival", "status": "at_gate", "scheduled_time": "2024-07-08T11:30:00"},
        {"id": "LIVE", "direction": "departure", "status": "boarding", "scheduled_time": "2024-07-08T11:50:00"},
        {"id": "FUT", "direction": "arrival", "status": "arrived", "scheduled_time": "2024-07-08T13:00:00"},
    ])
    db, _ = _passenger_db(monkeypatch, [])
    groups = {g["fid"]: g["statuses"] for g in db.reconciliation_groups(NOW)}
    # RC5: a departed flight also recovers everyone it left behind (→ missed_flight).
    assert groups == {
        "DEP": ["boarded", "booked", "checked_in", "security_queue", "airside", "at_gate"],
        "ARR": ["airborne", "booked", "checked_in", "boarded"],
    }


def test_departure_window_comes_from_the_view(monkeypatch):
    fv = _view_module()
    _fresh_view(fv, rows=[
        {"id": "D1", "direction": "departure", "status": "scheduled", "estimated_time": "2024-07-08T12:30:00",
         "gate_id": "B07", "pax_count": 100},
        {"id": "D2", "direction": "departure", "status": "boarding", "estimated_time": "2024-07-08T13:00:00",
         "gate_id": "B07", "pax_count": 50},
        {"id": "D3", "direction": "departure", "status": "scheduled", "estimated_time": "2024-07-08T16:00:00",
         "gate_id": "B07", "pax_count": 10},
    ])
    db, recorder = _passenger_db(monkeypatch, [])
    groups = asyncio.run(db.get_departure_flights_in_window(NOW, 90))
    assert groups == [{"terminal_id": "T-B", "flight_count": 2, "total_pax": 150}]
    assert recorder.calls == []


def test_reconcile_runs_at_boot_then_hourly(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    consumer = importlib.import_module("kafka.consumer")
    monkeypatch.setattr(consumer, "RECONCILE_BOOT_TICKS", 2)
    monkeypatch.setattr(consumer, "_reconcile_cadence", {"boot_ticks": 0, "last": None})
    t = datetime(2024, 7, 8, 12, 0)
    from datetime import timedelta
    due = [consumer._reconcile_due(t + timedelta(minutes=m)) for m in (0, 1, 2, 30, 61, 62)]
    assert due == [True, True, False, False, True, False]


def test_baggage_induction_read_uses_view_ids(monkeypatch):
    fv = _view_module()
    _fresh_view(fv, rows=[
        {"id": "D1", "direction": "departure", "status": "scheduled", "estimated_time": "2024-07-08T13:00:00",
         "gate_id": "B07"},
        {"id": "D2", "direction": "departure", "status": "scheduled", "estimated_time": "2024-07-08T18:00:00"},
        {"id": "D3", "direction": "departure", "status": "departed", "estimated_time": "2024-07-08T11:00:00"},
        {"id": "A1", "direction": "arrival", "status": "scheduled", "estimated_time": "2024-07-08T12:30:00"},
    ])
    import_service_module("baggage", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    sys.modules["metrics"] = metrics
    db = importlib.import_module("db.neo4j")
    recorder = _Recorder([{"id": "b1", "flight_id": "D1"}])
    monkeypatch.setattr(db, "get_driver", lambda: recorder)
    rows = asyncio.run(db.get_dropped_off_baggage_for_departures(datetime(2024, 7, 8, 13, 30)))
    query, params = recorder.calls[0]
    assert params["fids"] == ["D1", "D3"]
    assert "f.status" not in query and "ASSIGNED_TO" not in query
    assert rows[0]["terminal_id"] == "T-B" and rows[0]["flight_status"] == "scheduled"


@pytest.fixture(autouse=True)
def _reset_view():
    yield
    fv = sys.modules.get("_common.flight_view")
    if fv is not None:
        fv.VIEW.load([], [], None)


def test_terminal_falls_back_to_the_gate_prefix_on_a_cold_start():
    """Live RC6 validation: bootstrapped before Gate nodes existed → every bag in A."""
    fv = _view_module()
    view = _fresh_view(fv, rows=[{"id": "F1", "direction": "departure", "gate_id": "C12"}], gates=())
    assert view.get("F1")["terminal_id"] == "T-C"
    view.apply("FlightGateAssigned", {"flight_id": "F1", "new_gate_id": "B03"}, NOW)
    assert view.get("F1")["terminal_id"] == "T-B"


def test_flight_draw_markers_are_bounded_to_active_flights(monkeypatch):
    """RC2: once-per-flight draw sets no longer grow with every flight ever seen."""
    consumer = _flight_consumer(monkeypatch)
    state = consumer.FlightConsumerState()
    state.crew_delay_drawn = {"old", "live"}
    state.ctot_assigned = {"old"}
    state.diversion_drawn = {"live"}
    consumer._prune_draw_sets(state, {"live", "other"})
    assert state.crew_delay_drawn == {"live"}
    assert state.ctot_assigned == set()
    assert state.diversion_drawn == {"live"}


def test_equipment_failure_is_drawn_once_per_turnaround_not_per_aircraft(monkeypatch):
    """Each turnaround of an aircraft gets its own equipment-failure draw."""
    from types import SimpleNamespace
    consumer = _flight_consumer(monkeypatch)
    state = consumer.FlightConsumerState()
    monkeypatch.setattr(consumer, "_state", state)
    draws = []
    monkeypatch.setattr(consumer.random, "random", lambda: draws.append(1) or 1.0)

    def plan(arrival):
        return SimpleNamespace(arrival_flight_id=arrival, started_at=NOW, tasks={})

    state.turnaround_plans = {"N100AR": plan("A1")}
    consumer._check_equipment_failures(NOW)
    consumer._check_equipment_failures(NOW)          # same turnaround: no second draw
    assert len(draws) == 1 and state.equipment_failure_drawn == {"A1"}

    state.turnaround_plans = {"N100AR": plan("A2")}  # next rotation of the same aircraft
    consumer._check_equipment_failures(NOW)
    assert len(draws) == 2
    assert state.equipment_failure_drawn == {"A2"}   # marker of the finished turnaround dropped

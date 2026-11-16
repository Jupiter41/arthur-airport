"""RC5 — per-passenger show-up, aircraft-gated boarding, missed_flight outcome.

DATA_FLOW_REVIEW.md RC5: whole flights checked in at T-120 and hit security in
the same minute at T-45, passengers boarded aircraft that had already left,
and the no-show draw only sampled whoever was at the gate (0.08% instead of
3%). These tests pin the replacement model.
"""

import asyncio
import importlib
import json
import random
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import import_service_module

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))

from _common import show_up  # noqa: E402

DEP = datetime(2024, 7, 6, 12, 0)
NOW = datetime(2024, 7, 6, 10, 30)


# ── show-up / no-show model ────────────────────────────────────────────────


def test_show_up_draws_follow_beta_3_2_over_the_check_in_window():
    rng = random.Random(7)
    draws = [show_up.draw_show_up(DEP, rng) for _ in range(5000)]
    minutes_before = [(DEP - d).total_seconds() / 60 for d in draws]
    assert min(minutes_before) >= 45 and max(minutes_before) <= 180
    # Beta(3,2) mean 0.6 of the window → T-99; the spread is roughly two hours.
    assert 95 <= statistics.mean(minutes_before) <= 103
    q = statistics.quantiles(minutes_before, n=20)
    assert q[-1] - q[0] > 70
    assert all(d.second == 0 and d.microsecond == 0 for d in draws)  # fixed-width ISO


def test_legacy_passengers_get_a_deterministic_show_up():
    first = show_up.show_up_time("legacy-1", DEP.isoformat())
    assert first == show_up.show_up_time("legacy-1", DEP.isoformat())
    assert DEP - timedelta(minutes=180) <= first <= DEP - timedelta(minutes=45)
    stored = "2024-07-06T10:05:00"
    assert show_up.show_up_time("p", DEP, stored) == datetime(2024, 7, 6, 10, 5)


def test_no_show_draw_is_deterministic_and_matches_the_rate():
    ids = [f"pax-{i}" for i in range(40_000)]
    share = sum(show_up.is_no_show(pid, 0.03) for pid in ids) / len(ids)
    assert 0.027 <= share <= 0.033
    assert [show_up.is_no_show(p, 0.03) for p in ids[:200]] == \
           [show_up.is_no_show(p, 0.03) for p in ids[:200]]
    assert not any(show_up.is_no_show(p, 0.0) for p in ids[:1000])


def test_security_entry_after_check_in_processing_or_at_check_in_close():
    early = DEP - timedelta(minutes=120)
    assert not show_up.security_due(early, DEP, early + timedelta(minutes=9))
    assert show_up.security_due(early, DEP, early + timedelta(minutes=10))
    late = DEP - timedelta(minutes=50)
    assert show_up.security_due(late, DEP, DEP - timedelta(minutes=45))  # check-in close


def test_a_flights_cohort_reaches_security_spread_out_not_in_one_minute():
    rng = random.Random(3)
    entries = []
    for i in range(180):
        arrival = show_up.draw_show_up(DEP, rng)
        t = arrival
        while not show_up.security_due(arrival, DEP, t):
            t += timedelta(minutes=1)
        entries.append((DEP - t).total_seconds() / 60)
    assert len(set(entries)) > 60            # was 1 distinct minute (T-45)
    assert max(entries) - min(entries) > 90


def test_seeder_stores_show_up_for_departures_only():
    import_service_module("sim", "services.passengers")
    passengers = importlib.import_module("services.passengers")
    importlib.import_module("services.fixtures").load_fixtures()

    async def noop(*args, **kwargs):
        return None

    passengers._persist_passengers = noop
    passengers._update_flight_pax_counts = noop
    flight = {"id": "f1", "seat_capacity": 50, "scheduled_time": DEP.isoformat(),
              "origin_iata": "ART", "destination_iata": "ZZZ"}
    _, booked = asyncio.run(passengers.generate_passengers([flight], seed=1))
    _, arriving = asyncio.run(passengers.generate_passengers([flight], seed=1, initial_status="airborne"))
    assert all(p["show_up_at"] for p in booked)
    assert all(p["show_up_at"] is None for p in arriving)
    assert len({p["show_up_at"] for p in booked}) > 10
    # A separate RNG stream: names are identical with and without show-up draws.
    assert [p["name"] for p in booked] == [p["name"] for p in arriving]


# ── owner FSM ──────────────────────────────────────────────────────────────


@pytest.fixture
def consumer(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    module = importlib.import_module("kafka.consumer")
    state = module.PassengerConsumerState()
    monkeypatch.setattr(module, "_state", state)
    monkeypatch.setattr(module, "move_passenger", lambda *a: None)
    monkeypatch.setattr(module, "remove_passenger", lambda *a: None)
    return module


def _pax(pid, status, *, show_up_at=None, flight_status="scheduled", **extra):
    return {"id": pid, "status": status, "flight_id": "f1", "direction": "departure",
            "scheduled_time": DEP.isoformat(), "estimated_time": DEP.isoformat(),
            "flight_status": flight_status, "gate_id": "B04", "show_up_at": show_up_at, **extra}


def _no_show_id(rate=0.03):
    return next(f"ns-{i}" for i in range(10_000) if show_up.is_no_show(f"ns-{i}", rate))


def _show_id(rate=0.03, prefix="ok"):
    return next(f"{prefix}-{i}" for i in range(10_000) if not show_up.is_no_show(f"{prefix}-{i}", rate))


def test_check_in_releases_each_passenger_at_their_own_show_up(consumer, monkeypatch):
    due, later, absent = _show_id(prefix="due"), _show_id(prefix="later"), _no_show_id()
    reader = AsyncMock(return_value=[
        _pax(due, "booked", show_up_at="2024-07-06T10:20:00"),
        _pax(later, "booked", show_up_at="2024-07-06T10:40:00"),   # not yet
        _pax(absent, "booked", show_up_at="2024-07-06T09:00:00"),
    ])
    monkeypatch.setattr(consumer, "get_passengers_by_status", reader)
    plan = asyncio.run(consumer._advance_booked_to_checkin(NOW))
    assert plan.groups == [
        {"ids": [due], "status": "checked_in", "zone": "check-in-B"},
        {"ids": [absent], "status": "departed_airport", "zone": "no-show"},
    ]
    kwargs = reader.await_args.kwargs
    assert kwargs["due_field"] == "show_up_at" and kwargs["include_missing_due"] is True
    assert set(kwargs["flight_statuses"]) == {"scheduled", "boarding", "delayed"}


def test_security_entry_is_per_passenger(consumer, monkeypatch):
    ready, processing = _show_id(prefix="ready"), _show_id(prefix="proc")
    monkeypatch.setattr(consumer, "get_passengers_by_status", AsyncMock(return_value=[
        _pax(ready, "checked_in", show_up_at="2024-07-06T10:15:00"),
        _pax(processing, "checked_in", show_up_at="2024-07-06T10:25:00"),  # until 10:35
    ]))
    plan = asyncio.run(consumer._advance_checkin_to_security(NOW))
    assert plan.groups == [{"ids": [ready], "status": "security_queue", "zone": "security-B"}]
    assert consumer._state.security.get("B").queue_depth == 1


def test_boarding_never_reads_or_boards_a_departed_aircraft(consumer, monkeypatch):
    reader = AsyncMock(return_value=[
        _pax("p1", "at_gate", flight_status="boarding"),
        {**_pax("p2", "at_gate", flight_status="taxiing"), "flight_id": "f2"},  # never boarded
    ])
    monkeypatch.setattr(consumer, "get_passengers_by_status", reader)
    monkeypatch.setattr(consumer, "wheelchair", MagicMock(release=AsyncMock()))
    plan = asyncio.run(consumer._advance_boarding(DEP - timedelta(minutes=30)))
    assert set(reader.await_args.kwargs["flight_statuses"]) == {"scheduled", "boarding", "delayed"}
    boarded = [pid for g in plan.groups if g["status"] == "boarded" for pid in g["ids"]]
    assert boarded == ["p1"]


def test_gate_and_check_in_reads_exclude_departed_flights(consumer, monkeypatch):
    reader = AsyncMock(return_value=[])
    monkeypatch.setattr(consumer, "get_passengers_by_status", reader)
    asyncio.run(consumer._advance_airside_to_gate(NOW))
    asyncio.run(consumer._advance_checkin_to_security(NOW))
    for call in reader.await_args_list:
        assert set(call.kwargs["flight_statuses"]) == {"scheduled", "boarding", "delayed"}


def test_departure_sends_everyone_not_boarded_to_missed_flight(consumer, monkeypatch):
    from tests.unit.test_passenger_outbox import Driver
    db = importlib.import_module("db.neo4j")
    driver = Driver()
    monkeypatch.setattr(db, "get_driver", lambda: driver)
    consumer._state.security.enqueue("B", "queued")
    consumer._state.security_enqueued.add("queued")
    monkeypatch.setattr(consumer, "get_passengers_by_flight", AsyncMock(return_value=[
        {"id": "on-board", "status": "boarded", "location_zone": "gate-B04"},
        {"id": "queued", "status": "security_queue", "location_zone": "security-B"},
        {"id": "at-gate", "status": "at_gate", "location_zone": "gate-B04", "special_assistance": True},
        {"id": "late", "status": "booked", "location_zone": None},
        {"id": "gone", "status": "departed_airport", "location_zone": "no-show"},
    ]))
    released = AsyncMock()
    monkeypatch.setattr(consumer, "wheelchair", MagicMock(release=released))

    asyncio.run(consumer._on_flight_status_changed(
        {"flight_id": "f1", "new_status": "departed", "direction": "departure"}, NOW, "dep-1"))

    docs = [json.loads(row["document"]) for row in driver.db["outbox"].values()]
    outcome = {d["payload"]["passenger_id"]: d["payload"]["new_status"] for d in docs}
    assert outcome == {"on-board": "departed_airport", "queued": "missed_flight",
                       "at-gate": "missed_flight", "late": "missed_flight"}
    assert consumer._state.security.get("B").queue_depth == 0
    assert "queued" not in consumer._state.security_enqueued
    released.assert_awaited_once_with("at-gate", NOW)


def test_no_shows_are_off_the_boarding_manifest(monkeypatch):
    db = import_service_module("passenger", "db.neo4j")
    calls = []

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def run(self, query, **params):
            calls.append(query)

            class R:
                def __aiter__(self):
                    return self

                async def __anext__(self):
                    raise StopAsyncIteration
            return R()

    monkeypatch.setattr(db, "get_driver", lambda: type("D", (), {"session": lambda s: Session()})())
    asyncio.run(db.get_boarding_counts(["f1"]))
    assert "NOT (p.status = 'departed_airport' AND p.location_zone = 'no-show')" in calls[0]


def test_legacy_checkpoint_with_noshow_set_still_restores(consumer):
    state = consumer.PassengerConsumerState()
    stored = json.loads(consumer._TICK_CODEC.dump(state))
    stored["state"]["value"].append(["noshow_drawn_flights", {"type": "set", "value": ["f-old"]}])
    restored = consumer.PassengerConsumerState()
    consumer._TICK_CODEC.restore(restored, json.dumps(stored))
    assert not hasattr(restored, "noshow_drawn_flights")


def test_missed_flight_passengers_are_archived_by_retention(monkeypatch):
    import_service_module("passenger", "application.commands")
    metrics = ModuleType("metrics")
    metrics.__getattr__ = lambda name: MagicMock()
    monkeypatch.setitem(sys.modules, "metrics", metrics)
    retention = importlib.import_module("services.retention")
    queries = []

    class Tx:
        async def run(self, query, **params):
            queries.append(query)

            class R:
                async def data(self):
                    return []
            return R()

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def execute_write(self, fn):
            return await fn(Tx())

    monkeypatch.setattr(retention, "get_driver", lambda: type("D", (), {"session": lambda s: Session()})())
    asyncio.run(retention.archive_departed("2024-07-06T00:00:00", NOW, 10, "missed_flight"))
    assert "p.missed_flight_at < $before AND p.status = 'missed_flight'" in queries[0]
    *_, missed_task = retention.tasks(lambda: None, batch=10)
    assert missed_task.__name__ == "passenger_archive_missed_flight"

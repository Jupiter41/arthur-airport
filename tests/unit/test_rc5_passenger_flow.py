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
from collections import Counter
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


# ── warm start on a fresh simulation ───────────────────────────────────────


def _warm():
    import_service_module("passenger", "services.warm_start")
    return importlib.import_module("services.warm_start")


START = datetime(2024, 6, 15, 6, 0)


def _row(pid, dep, show):
    return {"id": pid, "flight_id": f"F{dep:%H%M}", "scheduled_time": dep.isoformat(),
            "show_up_at": show.isoformat()}


def test_warm_start_places_each_passenger_on_their_own_timeline():
    warm = _warm()
    dep = START + timedelta(minutes=150)               # 08:30
    ids = {n: _show_id(prefix=n) for n in ("future", "checkin", "security", "airside", "gate")}
    rows = [
        _row(ids["future"], dep, START + timedelta(minutes=5)),     # not due yet
        _row(ids["checkin"], dep, START - timedelta(minutes=4)),    # security at +6
        _row(ids["security"], dep, START - timedelta(minutes=12)),  # in lane until +3
        _row(ids["airside"], dep, START - timedelta(minutes=30)),   # airside since -15
    ]
    placed = {p.passenger_id: p for p in warm.place_departures(rows, START, 0.03, lambda _: 25)}
    assert ids["future"] not in placed
    assert placed[ids["checkin"]].status == "checked_in"
    assert placed[ids["security"]].status == "security_queue"
    assert placed[ids["airside"]].status == "airside"
    assert placed[ids["airside"]].dwell_remaining == 10         # 25 − 15 elapsed


def test_warm_start_no_shows_never_enter_the_airport():
    warm = _warm()
    pid = _no_show_id()
    rows = [_row(pid, START + timedelta(minutes=60), START - timedelta(minutes=40))]
    [placed] = warm.place_departures(rows, START, 0.03, lambda _: 25)
    assert placed.status == "departed_airport"


def test_warm_start_boards_at_the_boarding_rate_in_gate_arrival_order():
    warm = _warm()
    dep = START + timedelta(minutes=20)                # boarding call 05:45 → 15 min in
    rows = [_row(_show_id(prefix=f"g{i}"), dep, dep - timedelta(minutes=170)) for i in range(200)]
    placed = warm.place_departures(rows, START, 0.0, lambda _: 25)
    statuses = Counter(p.status for p in placed)
    assert statuses == {"boarded": 151, "at_gate": 49}     # ranks 0..150 within 15 min at 10/min


def test_warm_start_releases_only_a_few_minutes_of_arrivals_into_security():
    """The old first tick released every due passenger at once (≈4,100 at 06:00)."""
    warm = _warm()
    rng = random.Random(11)
    rows = []
    for f in range(60):
        dep = START + timedelta(minutes=10 + 5 * f)     # departures 06:10 … 11:05
        for i in range(150):
            rows.append(_row(f"w{f}-{i}", dep, show_up.draw_show_up(dep, rng)))
    placed = warm.place_departures(rows, START, 0.03, lambda _: 25)
    due = sum(1 for r in rows if datetime.fromisoformat(r["show_up_at"]) <= START)
    statuses = Counter(p.status for p in placed)
    assert len(placed) == due > 2000
    assert statuses["security_queue"] < 0.1 * due       # ~5 min of arrivals, not the backlog
    assert statuses["airside"] + statuses["at_gate"] + statuses["boarded"] > 0.5 * due


def test_first_tick_commits_the_warm_start_and_skips_placed_passengers(consumer, monkeypatch):
    pid_sec = _show_id(prefix="sec")
    pid_ci = _show_id(prefix="ci")
    dep = START + timedelta(minutes=150)
    rows = [
        {**_pax(pid_sec, "booked", show_up_at=(START - timedelta(minutes=12)).isoformat()),
         "scheduled_time": dep.isoformat(), "estimated_time": dep.isoformat()},
        {**_pax(pid_ci, "booked", show_up_at=(START - timedelta(minutes=4)).isoformat()),
         "scheduled_time": dep.isoformat(), "estimated_time": dep.isoformat()},
    ]
    reader = AsyncMock(return_value=rows)
    monkeypatch.setattr(consumer, "get_passengers_by_status", reader)
    plan = asyncio.run(consumer._warm_start_departures(START))
    assert {(g["status"], g["zone"]) : g["ids"] for g in plan.groups} == {
        ("security_queue", "security-B"): [pid_sec], ("checked_in", "check-in-B"): [pid_ci]}
    assert consumer._state.security.get("B").queue_depth == 1
    assert reader.await_args.kwargs["due_field"] == "show_up_at"
    # The same tick's check-in rule does not move them a second time.
    again = asyncio.run(consumer._advance_booked_to_checkin(START))
    assert again.groups == []


def test_warm_start_no_longer_writes_outside_the_tick_transaction(consumer):
    assert not hasattr(consumer, "bulk_update_status")
    assert not hasattr(consumer, "bulk_set_dwell")


def test_warm_start_waits_for_the_schedule_then_runs_once(consumer, monkeypatch):
    """Live regression: on a fresh stack the first tick beat FlightsScheduled."""
    fv = importlib.import_module("_common.flight_view")
    monkeypatch.setattr(consumer, "_warm_start_state", {"done": False})
    fv.VIEW.load([], [], None)
    assert not consumer._warm_start_due(1)          # empty view: nothing to place yet
    fv.VIEW.load([{"id": "D1", "direction": "departure", "status": "scheduled"}], [], None)
    assert consumer._warm_start_due(3)              # schedule arrived on tick 3
    consumer._mark_warm_start_done()
    assert not consumer._warm_start_due(4)          # never twice in one process
    monkeypatch.setattr(consumer, "_warm_start_state", {"done": False})
    assert not consumer._warm_start_due(consumer.WARM_START_WINDOW_TICKS + 1)  # mid-sim restart
    fv.VIEW.load([], [], None)

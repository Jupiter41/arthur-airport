"""Per-tick passenger reads are bounded to rows their transition rule can act on."""
import asyncio

import pytest

from tests.conftest import import_service_module


class _Result:
    def __aiter__(self):
        return self

    async def __anext__(self):
        raise StopAsyncIteration


class _Session:
    def __init__(self, calls):
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def run(self, query, **params):
        self.calls.append((query, params))
        return _Result()


def _db(monkeypatch):
    db = import_service_module("passenger", "db.neo4j")
    calls: list = []
    monkeypatch.setattr(db, "get_driver", lambda: type("D", (), {"session": lambda self: _Session(calls)})())
    return db, calls


def test_due_filter_bounds_by_passenger_timestamp_and_keeps_included_ids(monkeypatch):
    db, calls = _db(monkeypatch)
    asyncio.run(db.get_passengers_by_status(
        "baggage_claim", due_field="baggage_claim_at", due_at="2024-07-10T09:15:00",
        include_ids=["collected-1"],
    ))
    query, params = calls[0]
    assert "p.baggage_claim_at <= $due_at OR p.id IN $include_ids" in query
    assert params["due_at"] == "2024-07-10T09:15:00"
    assert params["include_ids"] == ["collected-1"]


def test_unbounded_read_is_unchanged(monkeypatch):
    db, calls = _db(monkeypatch)
    asyncio.run(db.get_passengers_by_status("security_queue"))
    assert "$due_at" not in calls[0][0] and "due_at" not in calls[0][1]


def test_due_filter_rejects_unknown_fields(monkeypatch):
    db, _ = _db(monkeypatch)
    with pytest.raises(ValueError, match="unsupported due filter"):
        asyncio.run(db.get_passengers_by_status("deplaning", due_field="name} DETACH DELETE p //",
                                                due_at="x"))


def test_connection_check_seeks_live_statuses_instead_of_scanning_label(monkeypatch):
    db, calls = _db(monkeypatch)
    asyncio.run(db.get_connecting_passengers())
    query, params = calls[0]
    assert "USING INDEX p:Passenger(status)" in query
    assert "{connection: true}" not in query
    excluded = {"departed_airport", "boarded", "missed_connection"}
    assert set(params["statuses"]).isdisjoint(excluded)
    assert {"booked", "airborne", "baggage_claim", "disrupted"} <= set(params["statuses"])

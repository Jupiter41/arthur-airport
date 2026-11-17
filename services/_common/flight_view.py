"""Event-fed view of flight state for non-owners (RC4).

Passenger-, baggage- and analysis-service used to join the live ``Flight`` nodes
in their decision queries. Those nodes are written by flight-service *ahead* of
the reader's position in ``flights.events``: a lagging passenger tick at sim T−3
saw flight state written at T, so reconciliation "stole" transitions before
their event arrived and stamped them with a time before their cause.

A ``FlightView`` holds exactly what the reader has consumed. It is fed by the
flight owner's facts (``FlightsScheduled``, ``FlightStatusChanged``,
``FlightGateAssigned``, ``FlightCancelled``, ``FlightDiverted``) and bootstrapped
once at startup from the flight owner's nodes, stamped with the reader's own
checkpoint time. Events at or before that stamp are already reflected in the
snapshot and are ignored; later ones advance the view in consumption order, so
the view always equals "flights as of the events this consumer processed".

Static topology (``Gate.terminal_id``) is read once at bootstrap; it does not
change while the sim runs. Graph reads keyed by flight *identity* (``ON_FLIGHT``,
``LOADED_ON`` with ``f.id IN $ids``) remain allowed — identity is not state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

FIELDS = (
    "flight_number", "direction", "status", "scheduled_time", "estimated_time",
    "actual_time", "delay_minutes", "gate_id", "flight_type", "pax_count",
    "destination_iata", "origin_iata", "aircraft_registration", "flight_duration_minutes",
)
HANDLED_EVENTS = frozenset({
    "FlightsScheduled", "FlightStatusChanged", "FlightGateAssigned",
    "FlightCancelled", "FlightDiverted", "FlightCTOTAssigned",
})
# Bootstrap reads flights whose schedule is within this window of the reader's clock.
BOOTSTRAP_PAST_H = 36
BOOTSTRAP_FUTURE_H = 48
# Flights finished longer ago than this leave the view (bounded memory).
EVICT_AFTER_H = 36
TERMINAL_STATUSES = frozenset({"departed", "airborne", "arrived", "completed", "cancelled", "diverted"})


def _iso(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:]:
        text = text[:10] + text[10:].split("+", 1)[0]
    return text


class FlightView:
    def __init__(self) -> None:
        self.flights: dict[str, dict] = {}
        self.gate_terminal: dict[str, str] = {}
        self.stamp: str | None = None  # bootstrap snapshot time (reader's clock)
        self.ready = False
        self.recovery_ids: set[str] = set()
        self.snapshot_ids: set[str] = set()

    # ── feeding ──────────────────────────────────────────────────

    def _terminal(self, gate_id: str | None) -> str | None:
        if not gate_id:
            return None
        known = self.gate_terminal.get(gate_id)
        if known:
            return known
        # Gate IDs encode their terminal ("B07" → "T-B"). On a cold start the
        # owner can bootstrap before the orchestrator seeds Gate nodes, leaving
        # the topology map empty for the life of the process; every bag then
        # fell back to terminal A (found live during RC6 validation).
        first = str(gate_id)[:1].upper()
        return f"T-{first}" if first.isalpha() else None

    def _merge(self, flight_id: str, values: dict, at: str | None) -> dict:
        record = self.flights.setdefault(flight_id, {"id": flight_id})
        for key in FIELDS:
            if key in values and values[key] is not None:
                value = values[key]
                if key.endswith("_time"):
                    value = _iso(value)
                record[key] = value
        record["terminal_id"] = self._terminal(record.get("gate_id")) or record.get("terminal_id")
        if at:
            record["updated_at"] = at
        return record

    def _stale(self, flight_id: str, at: str | None) -> bool:
        """True when this fact is already reflected (bootstrap stamp or newer change)."""
        if at is None:
            return False
        if flight_id in self.snapshot_ids and self.stamp is not None and at <= self.stamp:
            return True
        current = self.flights.get(flight_id, {}).get("updated_at")
        return current is not None and at < current

    def apply(self, event_type: str, payload: dict, sim_time: Any = None) -> bool:
        """Apply one consumed flight fact; returns True when the view changed."""
        if event_type not in HANDLED_EVENTS:
            return False
        at = _iso(sim_time)
        if event_type == "FlightsScheduled":
            changed = False
            for flight in payload.get("flights") or []:
                fid = flight.get("id")
                if fid and not self._stale(fid, at):
                    self._merge(fid, flight, at)
                    changed = True
            return changed
        fid = payload.get("flight_id")
        if not fid or self._stale(fid, at):
            return False
        if event_type == "FlightStatusChanged":
            values = dict(payload)
            values["status"] = payload.get("new_status")
            self._merge(fid, values, at)
        elif event_type == "FlightGateAssigned":
            self._merge(fid, {"gate_id": payload.get("new_gate_id"),
                              "flight_number": payload.get("flight_number")}, at)
        elif event_type == "FlightCancelled":
            self._merge(fid, {"status": "cancelled",
                              "flight_number": payload.get("flight_number")}, at)
        elif event_type == "FlightDiverted":
            self._merge(fid, {"status": "diverted",
                              "flight_number": payload.get("flight_number")}, at)
        elif event_type == "FlightCTOTAssigned":
            self._merge(fid, payload, at)  # pushed estimated_time / delay_minutes
        return True

    def load(self, rows: Iterable[dict], gates: Iterable[dict], stamp: datetime | None) -> None:
        """Install a bootstrap snapshot (rows shaped like ``FlightsScheduled.flights``)."""
        self.gate_terminal = {g["id"]: g.get("terminal_id") for g in gates if g.get("id")}
        self.stamp = _iso(stamp)
        self.flights = {}
        self.recovery_ids = set()
        for row in rows:
            if row.get("id"):
                self._merge(row["id"], row, None)
        self.snapshot_ids = set(self.flights)
        self.ready = True

    def evict(self, now: datetime) -> int:
        cutoff = (now.replace(tzinfo=None) - timedelta(hours=EVICT_AFTER_H)).isoformat()
        gone = [fid for fid, f in self.flights.items()
                if fid not in self.recovery_ids and f.get("status") in TERMINAL_STATUSES
                and (f.get("actual_time") or f.get("estimated_time") or f.get("scheduled_time") or "") < cutoff]
        for fid in gone:
            del self.flights[fid]
        return len(gone)

    # ── reading ──────────────────────────────────────────────────

    def get(self, flight_id: str | None) -> dict | None:
        return self.flights.get(flight_id) if flight_id else None

    def select(self, *, statuses: Iterable[str] | None = None, direction: str | None = None,
               scheduled_before: str | None = None, estimated_from: str | None = None,
               estimated_to: str | None = None, predicate: Callable[[dict], bool] | None = None,
               ) -> list[dict]:
        wanted = set(statuses) if statuses is not None else None
        out = []
        for flight in self.flights.values():
            if wanted is not None and flight.get("status") not in wanted:
                continue
            if direction is not None and flight.get("direction") != direction:
                continue
            if scheduled_before is not None and (flight.get("scheduled_time") or "") > scheduled_before:
                continue
            est = flight.get("estimated_time") or flight.get("scheduled_time") or ""
            if estimated_from is not None and est < estimated_from:
                continue
            if estimated_to is not None and est > estimated_to:
                continue
            if predicate is not None and not predicate(flight):
                continue
            out.append(flight)
        return out


# One view per service process, fed by its consumer and read by its repositories.
VIEW = FlightView()


BOOTSTRAP_FLIGHTS_QUERY = """
MATCH (f:Flight)
WHERE (f.scheduled_time >= $from AND f.scheduled_time <= $to)
   OR EXISTS { MATCH (:Baggage {status: 'in_hold'})-[:LOADED_ON]->(f)
               WHERE f.direction = 'arrival' }
OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
RETURN f.id AS id, f.flight_number AS flight_number, f.direction AS direction,
       f.status AS status, f.scheduled_time AS scheduled_time,
       f.estimated_time AS estimated_time, f.actual_time AS actual_time,
       f.delay_minutes AS delay_minutes, coalesce(g.id, f.gate_id) AS gate_id,
       f.flight_type AS flight_type, f.pax_count AS pax_count,
       f.destination_iata AS destination_iata, f.origin_iata AS origin_iata,
       f.aircraft_registration AS aircraft_registration,
       f.flight_duration_minutes AS flight_duration_minutes
"""
BOOTSTRAP_GATES_QUERY = "MATCH (g:Gate) RETURN g.id AS id, g.terminal_id AS terminal_id"


async def bootstrap(view: FlightView, get_driver: Callable[[], Any], stamp: datetime | None,
                    now: datetime | None = None) -> int:
    """One-time snapshot at startup (bootstrap only; the view is event-fed after)."""
    centre = (now or stamp or datetime(2024, 6, 15)).replace(tzinfo=None)
    async with get_driver().session() as session:
        gates = await (await session.run(BOOTSTRAP_GATES_QUERY)).data()
        rows = await (await session.run(
            BOOTSTRAP_FLIGHTS_QUERY,
            **{"from": (centre - timedelta(hours=BOOTSTRAP_PAST_H)).isoformat(),
               "to": (centre + timedelta(hours=BOOTSTRAP_FUTURE_H)).isoformat()},
        )).data()
    view.load(rows, gates, stamp)
    # Preserve old arrivals with outstanding holds until this process restarts.
    view.recovery_ids = {r["id"] for r in rows
                         if r.get("direction") == "arrival" and (r.get("scheduled_time") or "")
                         < (centre - timedelta(hours=BOOTSTRAP_PAST_H)).isoformat()}
    return len(rows)


def flight_record(flight: dict) -> dict:
    """The public flight record flight-service publishes (``FlightsScheduled`` rows)."""
    return {key: (_iso(flight.get(key)) if key.endswith("_time") else flight.get(key))
            for key in ("id", *FIELDS)}

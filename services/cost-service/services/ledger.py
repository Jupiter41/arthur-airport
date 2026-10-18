"""Atomic financial inbox, ledger, calculation checkpoint and event outbox."""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Awaitable, Callable
from uuid import uuid4

from neo4j import AsyncManagedTransaction
from pydantic import BaseModel, Field

from _common.financial_rates import load_default_rates, rates_version


class FinancialEnvelope(BaseModel):
    event_id: str = Field(min_length=1, strict=True)
    event_type: str
    sim_time: datetime
    payload: dict


@dataclass
class LedgerBatch:
    state: dict
    tx: AsyncManagedTransaction
    billing_day: int | None = None
    costs: list[dict] = field(default_factory=list)
    carbon: list[dict] = field(default_factory=list)


current_batch: ContextVar[LedgerBatch | None] = ContextVar("financial_batch", default=None)


def empty_day(day: int) -> dict:
    return {
        "cost": {"sim_day": day, "total_cost_eur": 0.0, "total_revenue_eur": 0.0,
                 "net_eur": 0.0, "by_category": {}, "eu261_exposure": 0.0, "last_updated": None},
        "carbon": {"sim_day": day, "total_kg": 0.0, "by_source": {}, "last_updated": None},
    }


def add_record(state: dict, record: dict, kind: str) -> None:
    day = int(record["sim_day"])
    totals = state["days"].setdefault(str(day), empty_day(day))[kind]
    totals["last_updated"] = record["sim_time"]
    if kind == "carbon":
        kg = record["co2_kg"]
        totals["total_kg"] += kg
        source = record["source"]
        totals["by_source"][source] = totals["by_source"].get(source, 0) + kg
    elif record["is_revenue"]:
        totals["total_revenue_eur"] += record["amount_eur"]
    else:
        amount, category = record["amount_eur"], record["category"]
        totals["total_cost_eur"] += amount
        totals["by_category"][category] = totals["by_category"].get(category, 0) + amount
        if category == "eu261_compensation":
            totals["eu261_exposure"] += amount
    if kind == "cost":
        totals["net_eur"] = totals["total_revenue_eur"] - totals["total_cost_eur"]


async def _locked_state(tx: AsyncManagedTransaction) -> tuple[dict, int]:
    result = await tx.run(
        "MERGE (s:CostRuntime {id: 'latest'}) "
        "SET s.revision = coalesce(s.revision, 0) + 1 "
        "RETURN s.document AS document, s.revision AS revision"
    )
    row = await result.single()
    if row["document"]:
        state = json.loads(row["document"])
        if "rates" not in state:
            state["rates"] = load_default_rates()
            state["rates_version"] = rates_version(state["rates"])
        return state, row["revision"]

    # One-time migration, under the same lock: preserve existing ledger totals.
    state = {"sim_day": 1, "gate_starts": {}, "last_staffing_hour": None, "days": {}}
    state["rates"] = load_default_rates()
    state["rates_version"] = rates_version(state["rates"])
    costs = await tx.run(
        "MATCH (c:CostRecord) RETURN c.sim_day AS sim_day, c.category AS category, "
        "c.is_revenue AS is_revenue, sum(c.amount_eur) AS amount_eur, max(c.sim_time) AS sim_time"
    )
    async for record in costs:
        add_record(state, dict(record), "cost")
    carbon = await tx.run(
        "MATCH (c:CarbonRecord) RETURN c.sim_day AS sim_day, c.source AS source, "
        "sum(c.co2_kg) AS co2_kg, max(c.sim_time) AS sim_time"
    )
    async for record in carbon:
        add_record(state, dict(record), "carbon")
    state["sim_day"] = max([int(day) for day in state["days"]] or [1])
    return state, row["revision"]


def event(kind: str, clock: str, payload: dict) -> dict:
    return {
        "event_id": str(uuid4()), "event_type": kind, "schema_version": "1.0",
        "producer": "cost-service", "produced_at": datetime.now(timezone.utc).isoformat(),
        "sim_time": clock, "payload": payload,
    }


async def _write_records(tx: AsyncManagedTransaction, rows: list[dict], kind: str, source_id: str) -> None:
    # Labels and relationship types are fixed by internal callers, never input.
    label = "CostRecord" if kind == "cost" else "CarbonRecord"
    result = await tx.run(
        f"UNWIND $rows AS row CREATE (c:{label}) SET c = row.record, c.source_event_id = $source_id "
        "WITH c, row OPTIONAL MATCH (f:Flight {id: row.flight_id}) "
        "FOREACH (_ IN CASE WHEN f IS NULL THEN [] ELSE [1] END | MERGE (c)-[:FOR_FLIGHT]->(f)) "
        "WITH c, row OPTIONAL MATCH (t:Terminal {id: row.terminal_id}) "
        "FOREACH (_ IN CASE WHEN t IS NULL THEN [] ELSE [1] END | MERGE (c)-[:FOR_TERMINAL]->(t)) "
        "WITH c, row OPTIONAL MATCH (i:Incident {id: row.incident_id}) "
        "FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END | MERGE (c)-[:CAUSED_BY]->(i)) "
        "WITH c, row OPTIONAL MATCH (a:Airport) "
        "FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END | "
        "MERGE (c)-[:FOR_DAY {day: row.record.sim_day}]->(a))",
        rows=rows, source_id=source_id,
    )
    await result.consume()


async def _write_effects(tx: AsyncManagedTransaction, batch: LedgerBatch, envelope: dict, revision: int) -> None:
    events = []
    for kind, rows in (("cost", batch.costs), ("carbon", batch.carbon)):
        for row in rows:
            row["record"]["rates_version"] = batch.state["rates_version"]
        if rows:
            await _write_records(tx, rows, kind, envelope["event_id"])
        for row in rows:
            record = row["record"]
            add_record(batch.state, record, kind)
            payload = dict(record, flight_id=row.get("flight_id"))
            payload["cost_record_id" if kind == "cost" else "carbon_record_id"] = payload.pop("id")
            if kind == "cost":
                payload["incident_id"] = row.get("incident_id")
            events.append(event("CostRecorded" if kind == "cost" else "CarbonRecorded", record["sim_time"], payload))
    events.append(event("FinancialEventProcessed", envelope["sim_time"], {
        "source_event_id": envelope["event_id"], "event_type": envelope["event_type"],
        "sim_day": batch.billing_day if batch.billing_day is not None else batch.state["sim_day"],
        "cost_record_ids": [r["record"]["id"] for r in batch.costs],
        "carbon_record_ids": [r["record"]["id"] for r in batch.carbon],
    }))
    # Keep the current and seven previous daily summaries; the full ledger stays.
    newest = max([int(day) for day in batch.state["days"]] + [batch.state["sim_day"]])
    batch.state["days"] = {key: val for key, val in batch.state["days"].items() if int(key) >= newest - 7}
    document = json.dumps(batch.state, allow_nan=False)
    result = await tx.run(
        "MATCH (s:CostRuntime {id: 'latest'}) SET s.document = $document "
        "CREATE (i:CostInbox {id: $id, sim_time: $sim_time})",
        document=document, id=envelope["event_id"], sim_time=envelope["sim_time"],
    )
    await result.consume()
    result = await tx.run(
        "UNWIND $events AS row CREATE (e:CostOutbox {id: row.id, document: row.document, "
        "revision: $revision, position: row.position})",
        events=[{"id": e["event_id"], "document": json.dumps(e, allow_nan=False), "position": n}
                for n, e in enumerate(events)], revision=revision,
    )
    await result.consume()


def publish_state(state: dict) -> None:
    from services import carbon_tracker, cost_engine

    day = state["sim_day"]
    current = state["days"].get(str(day), empty_day(day))
    cost_engine.init_running_totals(current["cost"])
    carbon_tracker.init_carbon_totals(current["carbon"])
    cost_engine._gate_occupancy_starts.clear()
    cost_engine._gate_occupancy_starts.update(state["gate_starts"])
    cost_engine.reset_daily_history()
    for key in sorted(state["days"], key=int):
        if int(key) >= day:
            continue
        cost = state["days"][key]["cost"]
        for signal in ("total_cost_eur", "total_revenue_eur", "eu261_exposure"):
            cost_engine._daily_history[signal].append(cost[signal])
        for category, amount in cost["by_category"].items():
            cost_engine._daily_history[f"by_category.{category}"].append(amount)


async def initialize() -> None:
    from db.neo4j import get_driver

    async def load(tx: AsyncManagedTransaction) -> dict:
        state, _ = await _locked_state(tx)
        result = await tx.run("MATCH (s:CostRuntime {id: 'latest'}) SET s.document = $document",
                              document=json.dumps(state, allow_nan=False))
        await result.consume()
        return state

    async with get_driver().session() as session:
        state = await session.execute_write(load)
    publish_state(state)


async def process(envelope: dict, dispatch: Callable[[dict], Awaitable[None]]) -> bool:
    from db.neo4j import get_driver

    async def apply(tx: AsyncManagedTransaction) -> tuple[bool, dict]:
        state, revision = await _locked_state(tx)
        seen = await (await tx.run("MATCH (i:CostInbox {id: $id}) RETURN i.id AS id", id=envelope["event_id"])).single()
        if seen:
            return False, state
        batch = LedgerBatch(state=state, tx=tx)
        token = current_batch.set(batch)
        try:
            if envelope["event_type"] == "SimClockTick":
                state["sim_day"] = int(envelope["payload"].get("day_of_sim", state["sim_day"]))
                state["clock_date"] = envelope["sim_time"]
            await dispatch(envelope)
            await _write_effects(tx, batch, envelope, revision)
        finally:
            current_batch.reset(token)
        return True, state

    async with get_driver().session() as session:
        processed, state = await session.execute_write(apply)
    # No awaits here: publish a coherent committed snapshot, including on retry
    # after a commit whose acknowledgement was lost by the previous attempt.
    publish_state(state)
    return processed

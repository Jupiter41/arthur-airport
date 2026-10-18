"""Cost-owned effective rates: serialized with ledger processing and outboxed."""

from __future__ import annotations

import json
import asyncio
import os

from neo4j import AsyncManagedTransaction

from _common.financial_rates import load_default_rates, merge_rates, rates_version
from db.neo4j import get_driver
from services import ledger


def from_state(state: dict) -> dict:
    return state.get("rates") or load_default_rates()


async def read() -> dict:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (s:CostRuntime {id: 'latest'}) RETURN s.document AS document",
        )
        row = await result.single()
    return from_state(json.loads(row["document"]) if row and row["document"] else {})


async def update(overrides: dict) -> dict:
    async def apply(tx: AsyncManagedTransaction) -> dict:
        state, revision = await ledger._locked_state(tx)
        candidate = merge_rates(from_state(state), overrides)
        version = rates_version(candidate)
        state["rates"] = candidate
        state["rates_version"] = version
        clock = state.get("clock_date") or "2026-01-01T00:00:00Z"
        fact = ledger.event("CostRatesUpdated", clock, {"rates": candidate, "version": version})
        await (await tx.run(
            "MATCH (s:CostRuntime {id: 'latest'}) SET s.document = $document",
            document=json.dumps(state, allow_nan=False),
        )).consume()
        await (await tx.run(
            "UNWIND $events AS row CREATE (e:CostOutbox {id: row.id, document: row.document, "
            "revision: $revision, position: row.position})",
            events=[{"id": fact["event_id"], "document": json.dumps(fact, allow_nan=False), "position": 0}],
            revision=revision,
        )).consume()
        return candidate

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def refresh_fuel_once() -> None:
    from services.fuel_price import fetch_fuel_price

    url = os.getenv("FUEL_PRICE_URL")
    if not url:
        return
    snapshot = await fetch_fuel_price(url)
    if snapshot is not None:
        await update({"delay_costs": {"fuel_price_per_kg_eur": snapshot["price_eur_per_kg"]}})


async def refresh_fuel_loop() -> None:
    from services.fuel_price import DEFAULT_REFRESH_S

    if not os.getenv("FUEL_PRICE_URL"):
        return
    while True:
        await asyncio.sleep(DEFAULT_REFRESH_S)
        await refresh_fuel_once()

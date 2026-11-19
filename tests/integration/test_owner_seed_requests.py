"""Real Neo4j transactions on isolated synthetic labels; opt in with RC7_NEO4J_URI."""
import asyncio
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "services"))
from _common import seed_requests  # noqa: E402

pytestmark = pytest.mark.skipif(not os.getenv("RC7_NEO4J_URI"), reason="isolated Neo4j not configured")


def test_owner_seeds_are_atomic_order_independent_and_replay_safe(monkeypatch):
    from neo4j import AsyncGraphDatabase

    async def run():
        driver = AsyncGraphDatabase.driver(os.environ["RC7_NEO4J_URI"], auth=(
            os.getenv("NEO4J_USER", "neo4j"), os.getenv("NEO4J_PASSWORD", "art-digital-twin")))
        prefix = "SeedTest" + uuid4().hex

        class Scoped:
            def __init__(self, connection):
                self.connection = connection

            def run(self, query, **params):
                query = re.sub(r":([A-Z][A-Za-z0-9_]*)", lambda m: ":" + prefix + m[1], query)
                return self.connection.run(query, **params)

            async def __aenter__(self):
                await self.connection.__aenter__()
                return self

            async def __aexit__(self, *args):
                return await self.connection.__aexit__(*args)

            async def execute_write(self, callback):
                async def apply(tx):
                    return await callback(Scoped(tx))
                return await self.connection.execute_write(apply)

        class Driver:
            def session(self):
                return Scoped(driver.session())

        scoped = Driver()
        now = datetime(2024, 6, 15, 6)
        manifests = {
            "flight": [{"id": "arrival", "gate_id": "A01", "runway_id": "09L",
                        "direction": "arrival", "status": "scheduled", "pax_count": 1}],
            "passenger": [{"id": "p1", "flight_id": "arrival", "status": "booked",
                           "connection": True, "connection_flight_id": "onward"}],
            "baggage": [{"id": "b1", "tag": "123", "flight_id": "arrival",
                         "passenger_id": "p1", "status": "in_hold", "transfer_flight_id": "onward"}],
        }
        try:
            async with scoped.session() as session:
                for label in ["SeedDay", "SeedBatch", "Flight", "Passenger", "Baggage"]:
                    await (await session.run(
                        f"CREATE CONSTRAINT {prefix}{label} FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                    )).consume()
                await (await session.run(
                    "CREATE (:Gate {id:'A01'}), (:Runway {id:'09L'}), "
                    "(:FlightRuntime {id:'latest'}), (:PassengerRuntime {id:'latest'}), "
                    "(:BaggageOutboxSeq {id:'latest'})"
                )).consume()
            # Competing seeders cannot store two versions of a day.
            stored = await asyncio.gather(*[
                seed_requests.store_day(lambda: scoped, "day1", now, manifests) for _ in range(2)
            ])
            assert sorted(stored) == [False, True]
            assert await seed_requests.apply_pending("baggage", lambda: scoped) == 0
            assert await seed_requests.apply_pending("passenger", lambda: scoped) == 0
            assert await seed_requests.apply_pending("flight", lambda: scoped) == 1
            assert await seed_requests.apply_pending("passenger", lambda: scoped) == 1

            original = seed_requests.outbox.stage_outbox

            async def fail(*args, **kwargs):
                raise RuntimeError("simulated outbox failure")

            with monkeypatch.context() as patch:
                patch.setattr(seed_requests.outbox, "stage_outbox", fail)
                with pytest.raises(RuntimeError, match="outbox failure"):
                    await seed_requests.apply_pending("baggage", lambda: scoped)
            async with scoped.session() as session:
                assert (await (await session.run("MATCH (b:Baggage) RETURN count(b) AS n")).single())["n"] == 0
            assert seed_requests.outbox.stage_outbox is original
            assert await seed_requests.apply_pending("baggage", lambda: scoped) == 1
            for owner in manifests:
                assert await seed_requests.apply_pending(owner, lambda: scoped) == 0
            async with scoped.session() as session:
                linked = await (await session.run(
                    "MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight), "
                    "(p)-[:CARRIES]->(b:Baggage)-[:LOADED_ON]->(f) "
                    "RETURN p.connection_flight_id AS onward, b.transfer_flight_id AS transfer, "
                    "b:UnscannedBaggage AS unscanned"
                )).single()
                assert dict(linked) == {"onward": "onward", "transfer": "onward", "unscanned": True}
                facts = await (await session.run(
                    "MATCH (o) WHERE o:FlightOutbox OR o:PassengerOutbox OR o:BaggageOutbox "
                    "RETURN o.document AS document"
                )).data()
                assert {json.loads(r["document"])["event_type"] for r in facts} == {
                    "FlightsScheduled", "PassengersSeeded", "BaggageSeeded",
                }
                assert (await (await session.run(
                    "MATCH (b:SeedBatch) WHERE b.pending = true OR b.document IS NOT NULL RETURN count(b) AS n"
                )).single())["n"] == 0
                # This old hold is outside the regular bootstrap window. The
                # startup projection must still include its flight for recovery.
                await (await session.run(
                    "MATCH (f:Flight {id:'arrival'}) SET f.status = 'arrived', "
                    "f.scheduled_time = '2024-06-01T10:00:00', f.actual_time = '2024-06-01T10:08:00'"
                )).consume()
            from _common.flight_view import FlightView, bootstrap
            view = FlightView()
            assert await bootstrap(view, lambda: scoped, now) == 1
            assert view.get("arrival")["status"] == "arrived"
            assert view.evict(now) == 0  # pinned until the next bootstrap
            # A baggage owner down across passenger archival still resolves
            # the existing identity, without creating a replacement passenger.
            async with scoped.session() as session:
                await (await session.run(
                    "MATCH (p:Passenger) REMOVE p:Passenger SET p:PassengerArchive"
                )).consume()
            await seed_requests.store_day(lambda: scoped, "late-day", now, {
                "baggage": [{**manifests["baggage"][0], "id": "late-bag", "tag": "124"}],
            })
            assert await seed_requests.apply_pending("baggage", lambda: scoped) == 1
            async with scoped.session() as session:
                linked = await (await session.run(
                    "MATCH (:PassengerArchive)-[:CARRIES]->(b:Baggage {id:'late-bag'}) "
                    "RETURN count(b) AS n"
                )).single()
                assert linked["n"] == 1
        finally:
            async with driver.session() as session:
                await (await session.run(
                    "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH $prefix) DETACH DELETE n",
                    prefix=prefix,
                )).consume()
                for label in ["SeedDay", "SeedBatch", "Flight", "Passenger", "Baggage"]:
                    await (await session.run(f"DROP CONSTRAINT {prefix}{label} IF EXISTS")).consume()
            await driver.close()

    asyncio.run(run())

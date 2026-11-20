"""Real Neo4j rollback/restart regression; requires the isolated RC14 test DB."""
import json
import os
from datetime import datetime
from uuid import uuid4

from neo4j import AsyncGraphDatabase
import pytest

from tests.conftest import import_service_module


@pytest.mark.asyncio
async def test_legacy_identity_atomic_rollback_and_idempotent_disposition(monkeypatch):
    uri = os.getenv("RC14_MIGRATION_TEST_URI")
    assert uri == "bolt://localhost:7688", "Run only against the isolated RC14 transaction database"
    module = import_service_module("baggage", "services.legacy_identity")
    prefix = "rc14-" + str(uuid4())
    monkeypatch.setattr(module, "MIGRATION", prefix)
    async with AsyncGraphDatabase.driver(uri, auth=("neo4j", "art-digital-twin")) as driver:
        monkeypatch.setattr(module, "get_driver", lambda: driver)
        await driver.execute_query("CREATE CONSTRAINT rc14_test_migration IF NOT EXISTS FOR (m:LegacyBaggageDisposition) REQUIRE m.id IS UNIQUE")
        await driver.execute_query("CREATE INDEX rc14_test_candidate IF NOT EXISTS FOR (b:LegacyBaggageCandidate) ON (b.id)")
        await driver.execute_query("""
        CREATE (p:Passenger {id:$id+'-p'}), (q:PassengerArchive {id:$id+'-q'}),
          (known:Baggage {id:$id+'-known',status:'in_hold'}),
          (anon:Baggage {id:$id+'-anon',status:'in_hold'}),
          (ambiguous:Baggage {id:$id+'-ambiguous',status:'flagged'}),
          (old:BaggageArchive {id:$id+'-old',status:'collected'}),
          (named:Baggage {id:$id+'-named',passenger_id:$id+'-p',status:'in_hold'}),
          (scan:ScanEvent {id:$id+'-scan',status:'in_hold'})
        CREATE (p)-[:CARRIES]->(known), (p)-[:CARRIES]->(ambiguous),
          (q)-[:CARRIES]->(ambiguous), (p)-[:CARRIES]->(named), (anon)-[:SCANNED_AT]->(scan)
        """, id=prefix)
        now = datetime(2024, 7, 29, 14)
        try:
            with pytest.raises(RuntimeError, match="durable simulation checkpoint"):
                await module.migrate_legacy_identity(None)
            original = module.outbox.stage_outbox
            async def fail(*args):
                raise RuntimeError("injected outbox failure")
            monkeypatch.setattr(module.outbox, "stage_outbox", fail)
            with pytest.raises(RuntimeError, match="injected outbox failure"):
                await module.classify_batch(now, batch=2)
            rows, _, _ = await driver.execute_query("MATCH (b:LegacyBaggageCandidate) RETURN count(*) AS n, count(b.passenger_id) AS named")
            assert rows[0]["n"] == 4 and rows[0]["named"] == 0
            monkeypatch.setattr(module.outbox, "stage_outbox", original)
            assert await module.classify_batch(now, batch=2) == 2
            await module.migrate_legacy_identity(now)
            rows, _, _ = await driver.execute_query("MATCH (m:LegacyBaggageDisposition {id:$id}) RETURN m.linked AS linked, m.quarantined AS quarantined", id=prefix)
            assert dict(rows[0]) == {"linked": 1, "quarantined": 3}
            rows, _, _ = await driver.execute_query("MATCH(b) WHERE b.id STARTS WITH $id RETURN b.id AS id, labels(b) AS labels, properties(b) AS properties", id=prefix)
            by_id = {r["id"].removeprefix(prefix+'-'): r for r in rows}
            assert by_id["known"]["properties"]["passenger_id"] == prefix+"-p"
            assert by_id["anon"]["properties"]["status"] == "in_hold"
            assert by_id["old"]["properties"]["legacy_original_label"] == "BaggageArchive"
            for key in ("anon", "old", "ambiguous"):
                assert by_id[key]["labels"] == ["LegacyBaggage"]
                assert "passenger_id" not in by_id[key]["properties"]
            assert by_id["scan"]["labels"] == ["LegacyScanEvent"]
            facts, _, _ = await driver.execute_query("MATCH(o:BaggageOutbox) RETURN o.document AS document")
            documents = [json.loads(r["document"]) for r in facts]
            documents = [d for d in documents if d["payload"].get("migration") == prefix]
            assert len(documents) == 2
            assert all(d["event_type"] == "BaggageIdentityDisposition" for d in documents)
            # Quarantined barcodes remain reserved during initial sequence migration.
            await driver.execute_query("MATCH(b:LegacyBaggage {id:$id}) SET b.tag = '8888000000'", id=prefix+'-old')
            from _common.seed_requests import allocate_baggage_tags
            allocated = [{}]
            async def allocate(tx):
                await allocate_baggage_tags(tx, allocated)
                await (await tx.run("MATCH(s:BaggageTagSequence {id:'global'}) SET s.rc14_test_owner=$id", id=prefix)).consume()
            async with driver.session() as session:
                await session.execute_write(allocate)
            assert int(allocated[0]["tag"]) > 8888000000
            await module.migrate_legacy_identity(now)
            rows, _, _ = await driver.execute_query("MATCH(m:LegacyBaggageDisposition {id:$id}) RETURN m.linked AS linked,m.quarantined AS quarantined", id=prefix)
            assert dict(rows[0]) == {"linked": 1, "quarantined": 3}
        finally:
            await driver.execute_query("MATCH(n) WHERE n.id STARTS WITH $id OR n.rc14_test_owner = $id DETACH DELETE n", id=prefix)

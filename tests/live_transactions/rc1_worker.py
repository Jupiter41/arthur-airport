"""Independent owner process for the RC1 real-database lifecycle regression."""
import asyncio
from datetime import datetime, timedelta
import json
import os
import sys

sys.path.insert(0, "/app")
sys.path.insert(0, "/g1-source")
from db import neo4j as db  # noqa: E402
from services import retention  # noqa: E402
from _common import outbox  # noqa: E402

ARGS = json.load(sys.stdin)
OWNER = ARGS["owner"]
NOW = datetime(2100, 1, 10, 12)
LABEL = "Passenger" if OWNER == "passenger" else "Baggage"


async def query(cypher, **params):
    async with db.get_driver().session() as session:
        return await (await session.run(cypher, **params)).data()


async def main():
    await db.init_neo4j()
    await db.create_constraints_and_indexes()
    # Fail closed even on non-seeding operations: never target an airport graph.
    foreign = await query("MATCH (n) WHERE n:Flight OR n:Passenger OR n:Baggage "
                          "WITH n WHERE NOT coalesce(n.id, '') STARTS WITH 'g1-' RETURN count(n) AS n")
    assert foreign[0]["n"] == 0, "RC1 requires a disposable database"
    mode = ARGS["mode"]
    if mode == "seed":
        # Same disposable G1 fixture contract as worker.py; never reset volumes.
        await query("MATCH (b:Baggage)-[:SCANNED_AT]->(s) WHERE b.id STARTS WITH 'g1-' DETACH DELETE s")
        await query("MATCH (n) WHERE n.id STARTS WITH 'g1-' DETACH DELETE n")
        for label in ("PassengerInbox", "BaggageInbox", "PassengerOutbox", "BaggageOutbox",
                      "PassengerRuntime", "BaggageOutboxSeq"):
            await query(f"MATCH (n:{label}) DETACH DELETE n")
        await query("CREATE (:Flight {id:'g1-rc1-diverted', direction:'arrival', status:'diverted', "
                    "scheduled_time:'2100-01-01T12:00:00', actual_time:'2100-01-01T12:01:00'})")
        if OWNER == "passenger":
            await query("UNWIND $rows AS row MATCH (f:Flight {id:'g1-rc1-diverted'}) "
                        "CREATE (:Passenger {id:row.id, status:row.status, missed_connection_at:row.at})-[:ON_FLIGHT]->(f)",
                        rows=[{"id": "g1-rc1-" + name, "status": status, "at": at} for name, status, at in [
                            ("old", "missed_connection", "2100-01-09T11:59:00"),
                            ("edge", "missed_connection", "2100-01-09T12:00:00"),
                            ("young", "missed_connection", "2100-01-10T11:00:00"),
                            ("active", "disrupted", "2100-01-01T12:00:00")]])
        else:
            await query("MATCH (f:Flight {id:'g1-rc1-diverted'}) "
                        "CREATE (p:Passenger {id:'g1-rc1-pax'}) "
                        "CREATE (b:Baggage:UnscannedBaggage {id:'g1-rc1-held', tag:'RC1-FAKE', "
                        "status:'in_hold', last_scan_at:'2100-01-01T12:00:00'})-[:LOADED_ON]->(f) "
                        "CREATE (p)-[:CARRIES]->(b) "
                        "CREATE (b)-[:SCANNED_AT]->(:ScanEvent {at:'2100-01-01T12:00:00'}) "
                        "CREATE (a:Flight {id:'g1-rc1-active-flight', direction:'arrival', status:'airborne', "
                        "scheduled_time:'2100-01-01T12:00:00'}) "
                        "CREATE (:Baggage {id:'g1-rc1-active', tag:'RC1-ACTIVE', status:'in_hold', "
                        "last_scan_at:'2100-01-01T12:00:00'})-[:LOADED_ON]->(a)")
    elif mode in ("recover", "rollback-recovery"):
        from kafka import consumer
        from _common.flight_view import VIEW, bootstrap
        await bootstrap(VIEW, db.get_driver, NOW)
        held = await query("MATCH (b:Baggage {id:'g1-rc1-held', status:'in_hold'}) RETURN b.id AS id")
        if held:
            assert VIEW.get("g1-rc1-diverted"), "Old outstanding holds must survive the bootstrap window"
        if mode == "rollback-recovery":
            original = outbox.stage_outbox

            async def fail(*args, **kwargs):
                raise RuntimeError("RC1 injected failure")

            outbox.stage_outbox = fail
            try:
                await consumer._reconcile_flight_baggage(NOW)
                raise AssertionError("Expected rollback")
            except RuntimeError as exc:
                assert str(exc) == "RC1 injected failure"
            finally:
                outbox.stage_outbox = original
        else:
            await consumer._reconcile_flight_baggage(NOW)
    elif mode in ("archive", "rollback-archive"):
        clock = NOW + timedelta(hours=ARGS.get("hours", 0))
        before = (clock - timedelta(hours=24)).isoformat()
        original = outbox.stage_outbox

        async def fail(*args, **kwargs):
            raise RuntimeError("RC1 injected failure")

        if mode == "rollback-archive":
            outbox.stage_outbox = fail
        try:
            if OWNER == "passenger":
                count = await retention.archive_departed(before, clock, 1, "missed_connection")
            else:
                count = await retention.archive_collected(before, clock, 1, "diverted")
            assert mode != "rollback-archive", "Expected rollback"
        except RuntimeError as exc:
            assert mode == "rollback-archive" and str(exc) == "RC1 injected failure"
            count = 0
        finally:
            outbox.stage_outbox = original
        print(json.dumps({"count": count}), flush=True)
    elif mode == "purge":
        clock = NOW + timedelta(hours=ARGS["hours"])
        count = await retention.purge_archived((clock - timedelta(hours=168)).isoformat(), clock, 1)
        print(json.dumps({"count": count}), flush=True)
    elif mode == "snapshot":
        nodes = await query(f"MATCH (n) WHERE (n:{LABEL} OR n:{LABEL}Archive) AND n.id STARTS WITH 'g1-rc1-' "
                            "RETURN n.id AS id, labels(n) AS labels, properties(n) AS p ORDER BY n.id")
        facts = await query(f"MATCH (e:{LABEL}Outbox) RETURN e.document AS document ORDER BY e.id")
        scans = await query("MATCH (b {id:'g1-rc1-held'})-[:SCANNED_AT]->(s) "
                            "RETURN labels(s) AS labels, s.status AS status, s.at AS at ORDER BY s.at")
        links = await query("MATCH (n) WHERE n.id STARTS WITH 'g1-rc1-' "
                            "RETURN n.id AS id, COUNT { (n)-[:ON_FLIGHT|LOADED_ON|CARRIES]->() } AS n ORDER BY n.id")
        archive_scans = await query("MATCH (s:ScanEventArchive) RETURN count(s) AS n")
        print(json.dumps({"nodes": nodes, "facts": [json.loads(f["document"]) for f in facts],
                          "scans": scans, "links": links, "archive_scans": archive_scans[0]["n"]}), flush=True)
    await db.close_neo4j()


assert os.getenv("G1_DISPOSABLE_STACK") == "1"
asyncio.run(main())

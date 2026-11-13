"""Neo4j async driver and Baggage persistence for baggage-service."""

import logging
from datetime import datetime

from neo4j import AsyncSession

from _common import neo4j_client

logger = logging.getLogger(__name__)

CONSTRAINTS = [
    "CREATE CONSTRAINT baggage_index_migration_id IF NOT EXISTS FOR (m:BaggageIndexMigration) REQUIRE m.id IS UNIQUE",
    "CREATE CONSTRAINT baggage_projection_id IF NOT EXISTS FOR (p:BaggageProjection) REQUIRE p.id IS UNIQUE",
    "CREATE CONSTRAINT commandreceipt_id IF NOT EXISTS FOR (r:CommandReceipt) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT baggage_tag IF NOT EXISTS FOR (b:Baggage) REQUIRE b.tag IS UNIQUE",
    # G1: durable inbox/outbox for the atomic domain-write + fact-delivery boundary
    # (mirrors cost-service db/neo4j.py CostInbox/CostOutbox).
    "CREATE CONSTRAINT baggage_inbox_id IF NOT EXISTS FOR (i:BaggageInbox) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT baggage_outbox_id IF NOT EXISTS FOR (o:BaggageOutbox) REQUIRE o.id IS UNIQUE",
    "CREATE CONSTRAINT baggage_outbox_seq_id IF NOT EXISTS FOR (s:BaggageOutboxSeq) REQUIRE s.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX unscanned_baggage_id IF NOT EXISTS FOR (b:UnscannedBaggage) ON (b.id)",
    "CREATE INDEX baggage_review_status IF NOT EXISTS FOR (b:Baggage) ON (b.review_status)",
    "CREATE INDEX baggage_page_scan IF NOT EXISTS FOR (b:Baggage) ON (b.last_scan_at, b.id)",
    "CREATE INDEX baggage_status IF NOT EXISTS FOR (b:Baggage) ON (b.status)",
    "CREATE INDEX baggage_id IF NOT EXISTS FOR (b:Baggage) ON (b.id)",
    "CREATE INDEX scan_event_baggage_tag IF NOT EXISTS FOR (s:ScanEvent) ON (s.baggage_tag)",
    # G1: deterministic (revision, position) delivery order for the outbox drainer.
    "CREATE INDEX baggage_outbox_order IF NOT EXISTS FOR (o:BaggageOutbox) ON (o.revision, o.position)",
]


async def init_neo4j() -> None:
    await neo4j_client.init_driver()


async def close_neo4j() -> None:
    await neo4j_client.close_driver()


def get_driver():
    return neo4j_client.get_driver()


async def check_neo4j() -> bool:
    return await neo4j_client.check_connectivity()


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    await neo4j_client.wait_for_driver(max_attempts=max_attempts, delay_s=delay_s)


async def create_constraints_and_indexes() -> None:
    driver = get_driver()
    async with driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await (await session.run(stmt)).consume()
        await _backfill_unscanned_index(session)
    logger.info("Baggage constraints and indexes created")


async def _backfill_unscanned_index(session: AsyncSession) -> None:
    """Idempotent metadata migration, with at most 1,000 label writes per commit."""
    marker = await (await session.run(
        "MATCH (m:BaggageIndexMigration {id:'unscanned-v1', ready:true}) RETURN m.id",
    )).single()
    if marker is not None:
        return
    await (await session.run(
        "MATCH (b:Baggage) WHERE b.last_scan_at IS NULL AND NOT b:UnscannedBaggage "
        "CALL { WITH b SET b:UnscannedBaggage } IN TRANSACTIONS OF 1000 ROWS",
    )).consume()
    await (await session.run(
        "MATCH (b:UnscannedBaggage) WHERE b.last_scan_at IS NOT NULL "
        "CALL { WITH b REMOVE b:UnscannedBaggage } IN TRANSACTIONS OF 1000 ROWS",
    )).consume()
    await (await session.run(
        "MERGE (m:BaggageIndexMigration {id:'unscanned-v1'}) SET m.ready=true",
    )).consume()


# ---------------------------------------------------------------------------
# Baggage CRUD
# ---------------------------------------------------------------------------

async def get_all_baggage(
    flight_id: str | None = None,
    passenger_id: str | None = None,
    status: str | None = None,
    flagged: bool | None = None,
    zone: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return baggage items with optional filters. Returns (items, total_count)."""
    driver = get_driver()

    where_clauses: list[str] = []
    matches = ["MATCH (b:Baggage)"]
    params: dict = {"limit": limit, "offset": offset}

    if flight_id:
        matches.append("MATCH (b)-[:LOADED_ON]->(:Flight {id: $flight_id})")
        params["flight_id"] = flight_id
    if passenger_id:
        matches.append("MATCH (:Passenger {id: $passenger_id})-[:CARRIES]->(b)")
        params["passenger_id"] = passenger_id
    if status:
        statuses = [s.strip() for s in status.split(",")]
        where_clauses.append("b.status IN $statuses")
        params["statuses"] = statuses
    if flagged is not None:
        where_clauses.append("b.is_dangerous_goods = $flagged")
        params["flagged"] = flagged
    if zone:
        where_clauses.append("b.last_scan_zone = $zone")
        params["zone"] = zone

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    match = "\n".join(matches)
    distinct = "DISTINCT " if flight_id or passenger_id else ""

    count_query = f"""
    {match}
    {where}
    RETURN count({distinct}b) AS total
    """
    data_query = f"""
    {match}
    {where}
    WITH {distinct}b
    ORDER BY b.last_scan_at DESC, b.id
    SKIP $offset LIMIT $limit
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    RETURN b {{
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    }} AS baggage,
    p.id AS passenger_id,
    p.name AS passenger_name,
    f.flight_number AS flight_number,
    f.id AS flight_id
    ORDER BY b.last_scan_at DESC, b.id
    """

    async with driver.session() as session:
        if not any((flight_id, passenger_id, status, zone)) and flagged is None:
            return await _unfiltered_baggage_page(session, limit, offset)
        count_result = await session.run(count_query, **params)
        count_record = await count_result.single()
        total = count_record["total"] if count_record else 0

        data_result = await session.run(data_query, **params)
        records = [record async for record in data_result]

    items = []
    for r in records:
        bag = dict(r["baggage"])
        bag["passenger_id"] = r["passenger_id"]
        bag["passenger_name"] = r["passenger_name"]
        bag["flight_number"] = r["flight_number"]
        bag["flight_id"] = r["flight_id"]
        items.append(bag)

    return items, total


async def _unfiltered_baggage_page(
    session: AsyncSession, limit: int, offset: int,
) -> tuple[list[dict], int]:
    """Read null and scanned groups in index order, including boundary pages."""
    total = (await (await session.run("MATCH (b:Baggage) RETURN count(b) AS n")).single())["n"]
    if offset >= total:
        return [], total
    unscanned = (await (await session.run(
        "MATCH (b:UnscannedBaggage) RETURN count(b) AS n",
    )).single())["n"]
    groups = []
    if offset < unscanned:
        groups.append(("UnscannedBaggage", "USING INDEX b:UnscannedBaggage(id)",
                       "b.id IS NOT NULL", "b.id DESC",
                       offset, min(limit, unscanned - offset)))
    remaining = limit - sum(group[5] for group in groups)
    if remaining:
        groups.append(("Baggage", "USING INDEX b:Baggage(last_scan_at, id)",
                       "b.last_scan_at IS NOT NULL AND b.id IS NOT NULL",
                       "b.last_scan_at DESC, b.id DESC", max(0, offset - unscanned), remaining))
    items = []
    for label, hint, predicate, ordering, skip, take in groups:
        result = await session.run(f"""
            MATCH (b:{label}) {hint} WHERE {predicate}
            WITH b ORDER BY {ordering} SKIP $skip LIMIT $take
            OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
            OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
            RETURN b {{.id, .tag, .status, .weight_kg, .is_dangerous_goods,
                       .dg_class, .last_scan_zone, .last_scan_at, .carousel}} AS baggage,
                   p.id AS passenger_id, p.name AS passenger_name,
                   f.flight_number AS flight_number, f.id AS flight_id
            ORDER BY {ordering}
        """, skip=skip, take=take)
        async for row in result:
            items.append(dict(row["baggage"], passenger_id=row["passenger_id"],
                              passenger_name=row["passenger_name"],
                              flight_number=row["flight_number"], flight_id=row["flight_id"]))
    return items, total


async def get_baggage_by_id(baggage_id: str) -> dict | None:
    """Get a single baggage item with scan history."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {id: $id})
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEvent)
    WITH b, p, f, s
    ORDER BY s.at ASC
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    } AS baggage,
    p { .id, .name, .pnr } AS passenger,
    f { .id, .flight_number, .status } AS flight,
    collect(s { .zone, .status, .at }) AS scan_history
    """
    async with driver.session() as session:
        result = await session.run(query, id=baggage_id)
        record = await result.single()
        if not record:
            return None
        bag = dict(record["baggage"])
        bag["passenger"] = dict(record["passenger"]) if record["passenger"] else None
        bag["flight"] = dict(record["flight"]) if record["flight"] else None
        bag["scan_history"] = [dict(s) for s in record["scan_history"]]
        return bag


async def get_baggage_by_tag(tag: str) -> dict | None:
    """Look up baggage by 10-digit barcode tag."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {tag: $tag})
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    OPTIONAL MATCH (b)-[:SCANNED_AT]->(s:ScanEvent)
    WITH b, p, f, s
    ORDER BY s.at ASC
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at, .carousel
    } AS baggage,
    p { .id, .name, .pnr } AS passenger,
    f { .id, .flight_number, .status } AS flight,
    collect(s { .zone, .status, .at }) AS scan_history
    """
    async with driver.session() as session:
        result = await session.run(query, tag=tag)
        record = await result.single()
        if not record:
            return None
        bag = dict(record["baggage"])
        bag["passenger"] = dict(record["passenger"]) if record["passenger"] else None
        bag["flight"] = dict(record["flight"]) if record["flight"] else None
        bag["scan_history"] = [dict(s) for s in record["scan_history"]]
        return bag


async def update_baggage_statuses(changes: list[dict], sim_time: datetime) -> None:
    """Persist independent bag transitions together, retaining every scan record."""
    if not changes:
        return
    async with get_driver().session() as session:
        result = await session.run(
            """
            UNWIND $changes AS change
            MATCH (b:Baggage {id: change.id})
            REMOVE b:UnscannedBaggage
            SET b.status = change.status, b.last_scan_zone = change.zone,
                b.last_scan_at = $at,
                b.carousel = coalesce(change.carousel, b.carousel)
            CREATE (s:ScanEvent {baggage_tag: b.tag, zone: change.zone,
                                 status: change.status, at: $at})
            CREATE (b)-[:SCANNED_AT]->(s)
            """,
            changes=changes, at=sim_time.isoformat(),
        )
        await result.consume()


# ---------------------------------------------------------------------------
# G1 — transaction-scoped writes (run INSIDE session.execute_write, alongside
# the BaggageInbox marker + BaggageOutbox staging, so the domain mutation and
# the facts to publish commit together or not at all).
# ---------------------------------------------------------------------------

async def write_baggage_statuses_tx(tx, changes: list[dict], sim_time: datetime) -> None:
    """Same batch mutation as ``update_baggage_statuses`` but on a managed tx.

    Writing the status + ScanEvent trail through the caller's transaction lets it
    be committed atomically with the inbox marker and the outbox facts.
    """
    if not changes:
        return
    result = await tx.run(
        """
        UNWIND $changes AS change
        MATCH (b:Baggage {id: change.id})
        REMOVE b:UnscannedBaggage
        SET b.status = change.status, b.last_scan_zone = change.zone,
            b.last_scan_at = $at,
            b.carousel = coalesce(change.carousel, b.carousel)
        CREATE (s:ScanEvent {baggage_tag: b.tag, zone: change.zone,
                             status: change.status, at: $at})
        CREATE (b)-[:SCANNED_AT]->(s)
        """,
        changes=changes, at=sim_time.isoformat(),
    )
    await result.consume()


async def flag_baggage_tx(
    tx,
    baggage_id: str,
    flag_reason: str,
    scan_zone: str,
    sim_time: datetime,
    review_status: str = "pending",
) -> None:
    """Flag a bag (status='flagged' + flag metadata + ScanEvent) on a managed tx.

    Transaction-scoped twin of :func:`flag_baggage` so a screening flag commits
    atomically with the inbox marker and the staged ``BaggageFlagged`` fact.
    """
    result = await tx.run(
        """
        MATCH (b:Baggage {id: $id})
        REMOVE b:UnscannedBaggage
        SET b.status = 'flagged',
            b.last_scan_zone = $zone,
            b.last_scan_at = $at,
            b.flag_reason = $flag_reason,
            b.flagged_at = $at,
            b.review_status = $review_status
        CREATE (s:ScanEvent {baggage_tag: b.tag, zone: $zone, status: 'flagged', at: $at})
        CREATE (b)-[:SCANNED_AT]->(s)
        """,
        id=baggage_id,
        zone=scan_zone,
        at=sim_time.isoformat(),
        flag_reason=flag_reason,
        review_status=review_status,
    )
    await result.consume()


async def set_loaded_on_timestamps_tx(tx, rows: list[dict], sim_time: datetime) -> None:
    """Set ``loaded_at`` on LOADED_ON for several bags, on a managed tx.

    ``rows`` is ``[{"baggage_id", "flight_id"}, ...]``. Lets the make-up / sorting
    "loaded" transition record its relationship timestamp inside the per-tick
    transaction rather than in a separate non-atomic write.
    """
    if not rows:
        return
    result = await tx.run(
        """
        UNWIND $rows AS row
        MATCH (b:Baggage {id: row.baggage_id})
        MATCH (f:Flight {id: row.flight_id})
        MERGE (b)-[r:LOADED_ON]->(f)
        SET r.loaded_at = $at
        """,
        rows=rows,
        at=sim_time.isoformat(),
    )
    await result.consume()


async def redirect_baggage_to_flight_tx(
    tx, baggage_id: str, target_flight_id: str, sim_time: datetime
) -> bool:
    """Re-assign LOADED_ON to a different flight on a managed tx (G1-b).

    Transaction-scoped twin of :func:`redirect_baggage_to_flight` so the bag
    redirect, the durable command receipt and the staged ``BaggageStatusChanged``
    fact all commit together. Returns True iff both nodes matched and the
    relationship was re-created.
    """
    result = await tx.run(
        """
        MATCH (b:Baggage {id: $bid})
        MATCH (f:Flight {id: $fid})
        OPTIONAL MATCH (b)-[old:LOADED_ON]->(:Flight)
        DELETE old
        CREATE (b)-[:LOADED_ON {redirected_at: $at}]->(f)
        REMOVE b:UnscannedBaggage
        SET b.last_scan_zone = 'redirected',
            b.last_scan_at = $at
        RETURN b.id AS id
        """,
        bid=baggage_id,
        fid=target_flight_id,
        at=sim_time.isoformat(),
    )
    record = await result.single()
    return record is not None


async def begin_tick_tx(tx, sim_time_iso: str) -> tuple[bool, int]:
    """Lock the baggage runtime checkpoint and decide whether to process a tick.

    Generalises cost-service's locked ``CostRuntime`` to the baggage tick FSM
    (A41 "per-tick, per-owner atomicity"). The single ``BaggageOutboxSeq`` node
    carries both the monotonic outbox ``revision`` and ``last_tick_sim_time``.
    MERGE takes the write lock. If ``sim_time_iso`` is not strictly after the
    recorded ``last_tick_sim_time`` the tick is a replay/crash-resume and the
    caller must early-return (``(False, 0)``) — nothing is mutated. Otherwise the
    revision is bumped and ``last_tick_sim_time`` advanced in the same tx, so a
    committed tick advances the checkpoint atomically with its writes.

    ISO-8601 naive timestamps compare correctly as strings (fixed format).
    """
    result = await tx.run(
        "MERGE (s:BaggageOutboxSeq {id: 'latest'}) "
        "RETURN s.last_tick_sim_time AS last_tick, coalesce(s.revision, 0) AS revision"
    )
    row = await result.single()
    last_tick = row["last_tick"]
    if last_tick is not None and sim_time_iso <= last_tick:
        return False, 0
    result = await tx.run(
        "MATCH (s:BaggageOutboxSeq {id: 'latest'}) "
        "SET s.revision = coalesce(s.revision, 0) + 1, "
        "    s.last_tick_sim_time = $last_tick "
        "RETURN s.revision AS revision",
        last_tick=sim_time_iso,
    )
    row = await result.single()
    return True, row["revision"]


async def next_outbox_revision_tx(tx) -> int:
    """Return the next monotonic outbox revision, bumped inside the caller's tx.

    A single ``BaggageOutboxSeq`` counter (mirroring cost-service's locked
    ``CostRuntime.revision``) gives every processed input a strictly increasing
    revision, so facts from different events never interleave in the drainer's
    ``ORDER BY revision, position``. The bump shares the caller's transaction, so
    a rolled-back event consumes no revision.
    """
    result = await tx.run(
        "MERGE (s:BaggageOutboxSeq {id: 'latest'}) "
        "SET s.revision = coalesce(s.revision, 0) + 1 "
        "RETURN s.revision AS revision"
    )
    row = await result.single()
    return row["revision"]


async def update_baggage_status(
    baggage_id: str,
    new_status: str,
    scan_zone: str,
    sim_time: datetime,
) -> dict | None:
    """Update baggage status, last scan info, and append a ScanEvent node."""
    driver = get_driver()
    sim_time_str = sim_time.isoformat()
    query = """
    MATCH (b:Baggage {id: $id})
    REMOVE b:UnscannedBaggage
    SET b.status = $status,
        b.last_scan_zone = $zone,
        b.last_scan_at = $at
    CREATE (s:ScanEvent {
        baggage_tag: b.tag,
        zone: $zone,
        status: $status,
        at: $at
    })
    CREATE (b)-[:SCANNED_AT]->(s)
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at
    } AS baggage
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            id=baggage_id,
            status=new_status,
            zone=scan_zone,
            at=sim_time_str,
        )
        record = await result.single()
        if not record:
            return None
        return dict(record["baggage"])


async def flag_baggage(
    baggage_id: str,
    flag_reason: str,
    scan_zone: str,
    sim_time: datetime,
    review_status: str = "pending",
) -> dict | None:
    """Flag a baggage item (DG detected or false positive)."""
    driver = get_driver()
    sim_time_str = sim_time.isoformat()
    query = """
    MATCH (b:Baggage {id: $id})
    REMOVE b:UnscannedBaggage
    SET b.status = 'flagged',
        b.last_scan_zone = $zone,
        b.last_scan_at = $at,
        b.flag_reason = $flag_reason,
        b.flagged_at = $at,
        b.review_status = $review_status
    CREATE (s:ScanEvent {
        baggage_tag: b.tag,
        zone: $zone,
        status: 'flagged',
        at: $at
    })
    CREATE (b)-[:SCANNED_AT]->(s)
    RETURN b {
        .id, .tag, .status, .weight_kg, .is_dangerous_goods,
        .dg_class, .last_scan_zone, .last_scan_at,
        .flag_reason, .flagged_at, .review_status
    } AS baggage
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            id=baggage_id,
            zone=scan_zone,
            at=sim_time_str,
            flag_reason=flag_reason,
            review_status=review_status,
        )
        record = await result.single()
        if not record:
            return None
        return dict(record["baggage"])


async def get_baggage_counts_by_status() -> dict[str, int]:
    """Get count of baggage items grouped by status."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage)
    USING INDEX b:Baggage(status)
    WHERE b.status IS NOT NULL
    RETURN b.status AS status, count(b) AS cnt
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["status"]: r["cnt"] for r in records if r["status"]}


async def get_baggage_by_zone(zone: str) -> list[dict]:
    """Get all baggage currently in a specific zone."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {last_scan_zone: $zone})
    WHERE b.status NOT IN ['collected', 'lost']
    RETURN b.id AS id, b.tag AS tag, b.status AS status
    """
    async with driver.session() as session:
        result = await session.run(query, zone=zone)
        return [dict(r) async for r in result]


async def get_flagged_baggage(limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
    """Page distinct flagged/pending bags before expanding display metadata."""
    driver = get_driver()
    candidates = """
    CALL {
        MATCH (b:Baggage {status: 'flagged'})
        USING INDEX b:Baggage(status)
        RETURN b
        UNION
        MATCH (b:Baggage {review_status: 'pending'})
        USING INDEX b:Baggage(review_status)
        RETURN b
    }
    """
    query = candidates + """
    WITH b ORDER BY b.id SKIP $offset LIMIT $limit
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    WITH b, p ORDER BY p.id
    WITH b, head(collect(p)) AS p
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    WITH b, p, f ORDER BY f.id
    WITH b, p, head(collect(f)) AS f
    RETURN b {
        .id, .tag, .status, .is_dangerous_goods, .dg_class,
        .last_scan_zone, .flag_reason, .flagged_at, .review_status
    } AS baggage,
    p.name AS passenger_name,
    f.flight_number AS flight_number
    ORDER BY b.id
    """
    async with driver.session() as session:
        count = await (await session.run(candidates + "RETURN count(b) AS total")).single()
        total = count["total"] if count else 0
        if offset >= total:
            return [], total
        result = await session.run(query, limit=limit, offset=offset)
        records = [record async for record in result]
    items = []
    for r in records:
        bag = dict(r["baggage"])
        bag["passenger_name"] = r["passenger_name"]
        bag["flight_number"] = r["flight_number"]
        items.append(bag)
    return items, total


async def get_flight_baggage(flight_id: str, statuses: list[str] | None = None) -> list[dict]:
    """Get all baggage loaded on a specific flight, optionally filtered by status."""
    driver = get_driver()
    status_filter = ""
    params: dict = {"fid": flight_id}
    if statuses:
        status_filter = "AND b.status IN $statuses"
        params["statuses"] = statuses
    query = f"""
        MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight {{id: $fid}})
        OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    WHERE true {status_filter}
    RETURN b.id AS id, b.tag AS tag, b.status AS status,
            b.last_scan_zone AS last_scan_zone,
            p.id AS passenger_id
    """
    async with driver.session() as session:
        result = await session.run(query, **params)
        return [dict(r) async for r in result]


async def get_dropped_off_baggage_for_departures(sim_time: datetime) -> list[dict]:
    """Get baggage in 'dropped_off' status linked to departure flights.
    Includes flights in any non-terminal state so we can catch up if the service
    started after flights had already departed."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {status: 'dropped_off'})-[:LOADED_ON]->(f:Flight)
    WHERE f.direction = 'departure'
      AND f.status <> 'cancelled'
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    RETURN b.id AS id, b.tag AS tag, b.is_dangerous_goods AS is_dg,
           b.dg_class AS dg_class, b.weight_kg AS weight_kg,
           f.id AS flight_id, f.flight_number AS flight_number,
           f.estimated_time AS estimated_time,
           f.status AS flight_status,
           p.id AS passenger_id,
           g.id AS gate_id,
           g.terminal_id AS terminal_id
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(r) async for r in result]


async def set_baggage_carousel(baggage_id: str, carousel: int, sim_time: datetime) -> None:
    """Set the carousel number for a baggage item."""
    get_driver()
    await _run_simple(
        "MATCH (b:Baggage {id: $id}) SET b.carousel = $carousel",
        id=baggage_id,
        carousel=carousel,
    )


async def _run_simple(query: str, **params) -> None:
    driver = get_driver()
    async with driver.session() as session:
        await session.run(query, **params)


async def set_loaded_on_timestamp(
    baggage_id: str, flight_id: str, sim_time: datetime
) -> None:
    """Set loaded_at on LOADED_ON, creating the relationship if needed."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage {id: $bid})
    MATCH (f:Flight {id: $fid})
    MERGE (b)-[r:LOADED_ON]->(f)
    SET r.loaded_at = $at
    """
    async with driver.session() as session:
        await session.run(
            query,
            bid=baggage_id,
            fid=flight_id,
            at=sim_time.isoformat(),
        )


async def redirect_baggage_to_flight(
    baggage_id: str, target_flight_id: str, sim_time: datetime
) -> bool:
    """Re-assign a baggage item's LOADED_ON relationship to a different flight.

    Returns True if both the bag and the target flight exist and the relationship
    was updated, False otherwise.
    """
    driver = get_driver()
    query = """
    MATCH (b:Baggage {id: $bid})
    MATCH (f:Flight {id: $fid})
    OPTIONAL MATCH (b)-[old:LOADED_ON]->(:Flight)
    DELETE old
    CREATE (b)-[:LOADED_ON {redirected_at: $at}]->(f)
    REMOVE b:UnscannedBaggage
    SET b.last_scan_zone = 'redirected',
        b.last_scan_at = $at
    RETURN b.id AS id
    """
    async with driver.session() as session:
        result = await session.run(
            query,
            bid=baggage_id,
            fid=target_flight_id,
            at=sim_time.isoformat(),
        )
        record = await result.single()
        return record is not None


async def get_baggage_in_pipeline() -> list[dict]:
    """Return actual queues; persisted status excludes historical bags from induction."""
    driver = get_driver()
    query = """
    MATCH (b:Baggage)
    WHERE b.status IN ['inducted', 'screening', 'sorting', 'arrived']
    OPTIONAL MATCH (b)-[:LOADED_ON]->(f:Flight)
    OPTIONAL MATCH (p:Passenger)-[:CARRIES]->(b)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    RETURN b.id AS id, b.tag AS tag, b.status AS status,
           coalesce(b.last_scan_zone, b.current_zone) AS current_zone,
           b.last_scan_at AS last_scan_at, f.id AS flight_id,
           b.is_dangerous_goods AS is_dg, b.dg_class AS dg_class,
           p.id AS passenger_id, g.id AS gate_id, g.terminal_id AS terminal_id
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(record) async for record in result]


async def get_active_system_failures() -> dict[str, str]:
    """Recover failure ownership, including contained incidents still under repair."""
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (i:Incident {type: 'system_failure'}) "
            "WHERE i.status IN ['active', 'contained'] "
            "RETURN i.id AS id, i.location AS location"
        )
        return {row["id"]: row["location"] async for row in result}


async def save_zone_projection(payload: dict) -> None:
    """Persist the owner's aggregate before publishing it to analysis."""
    import json

    async with get_driver().session() as session:
        result = await session.run(
            "MERGE (p:BaggageProjection {id: 'latest'}) SET p.document = $document",
            document=json.dumps(payload, allow_nan=False),
        )
        await result.consume()

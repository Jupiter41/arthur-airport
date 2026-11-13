"""Neo4j async driver and Passenger persistence for passenger-service."""

import logging
from datetime import datetime

from _common import neo4j_client
from _common import outbox as _outbox

logger = logging.getLogger(__name__)

CONSTRAINTS = [
    "CREATE CONSTRAINT commandreceipt_id IF NOT EXISTS FOR (r:CommandReceipt) REQUIRE r.id IS UNIQUE",
    "CREATE CONSTRAINT security_checkpoint_terminal IF NOT EXISTS FOR (s:SecurityCheckpoint) REQUIRE s.terminal IS UNIQUE",
    "CREATE CONSTRAINT passenger_id IF NOT EXISTS FOR (p:Passenger) REQUIRE p.id IS UNIQUE",
    # 1C — Accessibility & special assistance pool
    "CREATE CONSTRAINT wheelchair_resource_terminal IF NOT EXISTS FOR (w:WheelchairResource) REQUIRE w.terminal IS UNIQUE",
    "CREATE CONSTRAINT wheelchair_assignment_id IF NOT EXISTS FOR (a:WheelchairAssignment) REQUIRE a.id IS UNIQUE",
    # G1 — transactional domain-write + outbox/inbox (mirrors cost-service)
    "CREATE CONSTRAINT passenger_inbox_id IF NOT EXISTS FOR (i:PassengerInbox) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT passenger_outbox_id IF NOT EXISTS FOR (o:PassengerOutbox) REQUIRE o.id IS UNIQUE",
    # G1-a — per-tick, per-owner locked runtime checkpoint (mirrors CostRuntime/FlightRuntime)
    "CREATE CONSTRAINT passenger_runtime_id IF NOT EXISTS FOR (s:PassengerRuntime) REQUIRE s.id IS UNIQUE",
]

INDEXES = [
    "CREATE INDEX passenger_outbox_order IF NOT EXISTS FOR (o:PassengerOutbox) ON (o.revision, o.position)",
    "CREATE INDEX passenger_pnr IF NOT EXISTS FOR (p:Passenger) ON (p.pnr)",
    "CREATE INDEX passenger_status IF NOT EXISTS FOR (p:Passenger) ON (p.status)",
    "CREATE INDEX passenger_location IF NOT EXISTS FOR (p:Passenger) ON (p.location_zone)",
    "CREATE INDEX passenger_flight IF NOT EXISTS FOR (p:Passenger) ON (p.flight_id)",
    "CREATE INDEX flight_scheduled IF NOT EXISTS FOR (f:Flight) ON (f.scheduled_time)",
    "CREATE INDEX flight_direction IF NOT EXISTS FOR (f:Flight) ON (f.direction)",
    # 1C — find recent assignments by hour for staffing analytics
    "CREATE INDEX wheelchair_assignment_terminal IF NOT EXISTS FOR (a:WheelchairAssignment) ON (a.terminal)",
    "CREATE INDEX wheelchair_assignment_requested IF NOT EXISTS FOR (a:WheelchairAssignment) ON (a.requested_at)",
]


async def init_neo4j() -> None:
    await neo4j_client.init_driver()


async def close_neo4j() -> None:
    await neo4j_client.close_driver()


def get_driver():
    from _common.transaction_scope import current, borrowed, TransactionDriver
    scope = current.get() or borrowed.get()
    return TransactionDriver(scope) if scope is not None else neo4j_client.get_driver()


async def check_neo4j() -> bool:
    return await neo4j_client.check_connectivity()


async def wait_for_neo4j(max_attempts: int = 12, delay_s: float = 5) -> None:
    await neo4j_client.wait_for_driver(max_attempts=max_attempts, delay_s=delay_s)


async def create_constraints_and_indexes() -> None:
    driver = get_driver()
    async with driver.session() as session:
        for stmt in CONSTRAINTS + INDEXES:
            await session.run(stmt)
        await (await session.run("MERGE (s:PassengerRuntime {id: 'latest'})")).consume()
    logger.info("Passenger constraints and indexes created")


# ---------------------------------------------------------------------------
# Passenger CRUD
# ---------------------------------------------------------------------------

async def get_all_passengers(
    flight_id: str | None = None,
    flight_number: str | None = None,
    status: str | None = None,
    zone: str | None = None,
    connection: bool | None = None,
    special_assistance: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Return passengers with optional filters. Returns (items, total)."""
    driver = get_driver()

    where_clauses: list[str] = []
    params: dict = {"limit": limit, "offset": offset}

    if flight_id:
        where_clauses.append("f.id = $flight_id")
        params["flight_id"] = flight_id
    if flight_number:
        where_clauses.append("f.flight_number = $flight_number")
        params["flight_number"] = flight_number
    if status:
        statuses = [s.strip() for s in status.split(",")]
        where_clauses.append("p.status IN $statuses")
        params["statuses"] = statuses
    if zone:
        where_clauses.append("p.location_zone = $zone")
        params["zone"] = zone
    if connection is not None:
        where_clauses.append("p.connection = $connection")
        params["connection"] = connection
    if special_assistance is not None:
        where_clauses.append("p.special_assistance = $sa")
        params["sa"] = special_assistance

    where = "WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    count_query = f"""
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
    {where}
    RETURN count(p) AS total
    """
    data_query = f"""
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
    {where}
    RETURN p {{
        .id, .name, .pnr, .status, .location_zone, .seat,
        .connection, .special_assistance
    }} AS passenger,
    f.flight_number AS flight_number
    ORDER BY p.name
    SKIP $offset LIMIT $limit
    """

    async with driver.session() as session:
        count_result = await session.run(count_query, **params)
        count_record = await count_result.single()
        total = count_record["total"] if count_record else 0

        data_result = await session.run(data_query, **params)
        records = [record async for record in data_result]

    items = []
    for r in records:
        pax = dict(r["passenger"])
        pax["flight_number"] = r["flight_number"]
        items.append(pax)

    return items, total


async def get_passenger_by_id(passenger_id: str) -> dict | None:
    """Get full passenger detail with flight, baggage, and timeline."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger {id: $id})-[:ON_FLIGHT]->(f:Flight)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
    OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
    RETURN p {
        .id, .name, .pnr, .nationality, .status, .location_zone,
        .seat, .connection, .connection_flight_id, .special_assistance,
        .checked_in_at, .security_queue_at, .airside_at, .at_gate_at,
        .boarded_at, .deplaning_at, .baggage_claim_at, .departed_airport_at,
        .dwell_minutes, .connection_risk
    } AS passenger,
    f { .id, .flight_number, .status, .estimated_time, .scheduled_time } AS flight,
    g.id AS gate_id,
    collect(b { .tag, .status }) AS baggage
    """
    async with driver.session() as session:
        result = await session.run(query, id=passenger_id)
        record = await result.single()
        if not record:
            return None
        pax = dict(record["passenger"])
        flight_data = dict(record["flight"]) if record["flight"] else {}
        flight_data["gate_id"] = record["gate_id"]
        pax["flight"] = flight_data
        pax["baggage"] = [dict(b) for b in record["baggage"]]

        # Build timeline from timestamp fields
        timeline = []
        for status_key, ts_key in [
            ("checked_in", "checked_in_at"),
            ("security_queue", "security_queue_at"),
            ("airside", "airside_at"),
            ("at_gate", "at_gate_at"),
            ("boarded", "boarded_at"),
            ("deplaning", "deplaning_at"),
            ("baggage_claim", "baggage_claim_at"),
            ("departed_airport", "departed_airport_at"),
        ]:
            ts = pax.get(ts_key)
            if ts:
                timeline.append({"status": status_key, "at": ts})
        pax["timeline"] = timeline

        return pax


async def search_passengers(pnr: str | None = None, name: str | None = None) -> list[dict]:
    """Search passengers by PNR or partial name."""
    driver = get_driver()
    if pnr:
        query = """
        MATCH (p:Passenger {pnr: $pnr})-[:ON_FLIGHT]->(f:Flight)
        RETURN p { .id, .name, .pnr, .status, .location_zone } AS passenger,
               f.flight_number AS flight_number
        LIMIT 10
        """
        params = {"pnr": pnr.upper()}
    elif name:
        query = """
        MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight)
        WHERE toLower(p.name) CONTAINS toLower($name)
        RETURN p { .id, .name, .pnr, .status, .location_zone } AS passenger,
               f.flight_number AS flight_number
        LIMIT 20
        """
        params = {"name": name}
    else:
        return []

    async with driver.session() as session:
        result = await session.run(query, **params)
        records = [record async for record in result]
    items = []
    for r in records:
        pax = dict(r["passenger"])
        pax["flight_number"] = r["flight_number"]
        items.append(pax)
    return items


_VALID_STATUSES = frozenset({
    "booked", "checked_in", "security_queue", "airside", "at_gate",
    "boarded", "deplaning", "customs", "baggage_claim", "departed_airport",
    "missed_connection", "disrupted", "no_show", "cancelled",
})


async def update_passenger_status(
    passenger_id: str, new_status: str, new_zone: str, sim_time: datetime,
) -> dict | None:
    """Update passenger status and location zone, setting the timestamp field."""
    if new_status not in _VALID_STATUSES:
        raise ValueError(f"Invalid passenger status: {new_status!r}")
    driver = get_driver()
    ts_field = f"{new_status}_at"
    sim_str = sim_time.isoformat()
    query = f"""
    MATCH (p:Passenger {{id: $id}})
    SET p.status = $status,
        p.location_zone = $zone,
        p.{ts_field} = $ts
    RETURN p.id AS id, p.status AS status, p.location_zone AS zone
    """
    async with driver.session() as session:
        result = await session.run(
            query, id=passenger_id, status=new_status, zone=new_zone, ts=sim_str,
        )
        record = await result.single()
        return dict(record) if record else None


async def bulk_update_status(
    passenger_ids: list[str], new_status: str, new_zone: str, sim_time: datetime,
) -> int:
    """Bulk update status for multiple passengers. Returns count updated."""
    if not passenger_ids:
        return 0
    if new_status not in _VALID_STATUSES:
        raise ValueError(f"Invalid passenger status: {new_status!r}")
    driver = get_driver()
    ts_field = f"{new_status}_at"
    sim_str = sim_time.isoformat()
    query = f"""
    UNWIND $ids AS pid
    MATCH (p:Passenger {{id: pid}})
    SET p.status = $status,
        p.location_zone = $zone,
        p.{ts_field} = $ts
    RETURN count(p) AS cnt
    """
    from _common.transaction_scope import current
    scope = current.get()
    if scope is not None and passenger_ids:
        scope.facts.extend(_outbox.transition_batch_facts(
            "PassengerStatusBatchChanged", sim_time, "passenger-service", {
                "status_groups": [{"ids": passenger_ids, "status": new_status, "zone": new_zone}],
                "dwell_items": [], "location_updates": [], "risk_updates": [],
            }, grouped_ids={"status_groups": "ids"},
        ))
    async with driver.session() as session:
        result = await session.run(
            query, ids=passenger_ids, status=new_status, zone=new_zone, ts=sim_str,
        )
        record = await result.single()
        return record["cnt"] if record else 0



async def apply_status_change_atomic(
    event_id: str,
    groups: list[dict],
    facts: list[dict],
    sim_time: datetime,
) -> bool:
    """Atomic domain-write + inbox + outbox for a passenger status change (G1).

    Within ONE ``session.execute_write`` transaction (mirrors cost-service's
    ``ledger.process``) this:

      (a) skips if the input ``event_id`` is already in ``PassengerInbox`` —
          durable, restart-surviving dedup (stronger than the in-memory
          IdempotencyTracker, which is lost on restart);
      (b) bulk-updates passenger ``status`` / ``location_zone`` / ``<status>_at``
          — the authoritative domain write (Neo4j is the source of truth);
      (c) marks ``PassengerInbox`` so a redelivered input is not re-applied;
      (d) stages the ``PassengerStatusChanged`` facts into ``PassengerOutbox``
          instead of emitting them directly, so domain write and fact delivery
          commit or roll back together (rule #4: every state change emits an
          event — now transactionally).

    ``groups`` is a list of ``{"ids", "status", "zone"}`` transitions (one input
    event may move distinct cohorts to distinct statuses). ``facts`` is a list of
    ``{"id": <stable event_id>, "document": <full envelope>}`` outbox rows.

    Returns True if applied, False if ``event_id`` was already processed.

    A locked PassengerRuntime counter supplies a monotonic outbox revision
    shared with tick and command transactions; per-fact position orders the
    facts inside one committed input.
    """
    for group in groups:
        if group["status"] not in _VALID_STATUSES:
            raise ValueError(f"Invalid passenger status: {group['status']!r}")
    sim_str = sim_time.isoformat()

    async def apply(tx) -> bool:
        if await _outbox.inbox_seen(tx, "PassengerInbox", event_id):
            return False
        revision = await next_outbox_revision(tx)
        for group in groups:
            ids = group["ids"]
            if not ids:
                continue
            # ts_field derives from a status validated against _VALID_STATUSES
            # above, never from free input — safe to interpolate (as bulk_update_status does).
            ts_field = f"{group['status']}_at"
            result = await tx.run(
                f"UNWIND $ids AS pid "
                f"MATCH (p:Passenger {{id: pid}}) "
                f"SET p.status = $status, p.location_zone = $zone, p.{ts_field} = $ts",
                ids=ids, status=group["status"], zone=group["zone"], ts=sim_str,
            )
            await result.consume()
        await _outbox.mark_inbox(tx, "PassengerInbox", event_id, sim_str)
        await _outbox.stage_outbox(tx, "PassengerOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def _write_status_groups(tx, groups: list[dict], sim_str: str) -> None:
    """Bulk status/zone/timestamp writes for one or more transition cohorts."""
    for group in groups:
        ids = group["ids"]
        if not ids:
            continue
        # ts_field derives from a status already validated against _VALID_STATUSES
        # by the caller, never from free input — safe to interpolate.
        ts_field = f"{group['status']}_at"
        result = await tx.run(
            f"UNWIND $ids AS pid "
            f"MATCH (p:Passenger {{id: pid}}) "
            f"SET p.status = $status, p.location_zone = $zone, p.{ts_field} = $ts",
            ids=ids, status=group["status"], zone=group["zone"], ts=sim_str,
        )
        await result.consume()


async def _write_location_updates(tx, location_updates: list[dict]) -> None:
    """Location-only writes (no status/timestamp change) — e.g. carousel moves."""
    rows = [{"id": u["id"], "zone": u["zone"]} for u in location_updates if u.get("id")]
    if not rows:
        return
    result = await tx.run(
        "UNWIND $rows AS r MATCH (p:Passenger {id: r.id}) SET p.location_zone = r.zone",
        rows=rows,
    )
    await result.consume()


async def _write_risk_updates(tx, risk_updates: list[dict]) -> None:
    """Connection-risk property writes staged in the same transaction."""
    rows = [{"id": u["id"], "risk": u["risk"]} for u in risk_updates if u.get("id")]
    if not rows:
        return
    result = await tx.run(
        "UNWIND $rows AS r MATCH (p:Passenger {id: r.id}) SET p.connection_risk = r.risk",
        rows=rows,
    )
    await result.consume()


async def apply_changes_atomic(
    event_id: str,
    sim_time: datetime,
    *,
    status_groups: list[dict] | None = None,
    location_updates: list[dict] | None = None,
    risk_updates: list[dict] | None = None,
    facts: list[dict] | None = None,
) -> bool:
    """Generalized atomic domain-write + inbox + outbox for a discrete input (G1-c).

    Mirrors :func:`apply_status_change_atomic` but also stages location-only and
    connection-risk property writes, and allows ``facts`` to carry non-status
    envelopes (e.g. ``PassengerAlert``). Everything commits in ONE
    ``execute_write``: durable inbox dedup on ``event_id`` → status/location/risk
    writes → inbox marker → outbox facts at the locked owner runtime revision. Returns True if
    applied, False if ``event_id`` was already processed (durable dedup).
    """
    status_groups = status_groups or []
    location_updates = location_updates or []
    risk_updates = risk_updates or []
    facts = facts or []
    for group in status_groups:
        if group["status"] not in _VALID_STATUSES:
            raise ValueError(f"Invalid passenger status: {group['status']!r}")
    sim_str = sim_time.isoformat()

    async def apply(tx) -> bool:
        if await _outbox.inbox_seen(tx, "PassengerInbox", event_id):
            return False
        revision = await next_outbox_revision(tx)
        await _write_status_groups(tx, status_groups, sim_str)
        await _write_location_updates(tx, location_updates)
        await _write_risk_updates(tx, risk_updates)
        await _outbox.mark_inbox(tx, "PassengerInbox", event_id, sim_str)
        await _outbox.stage_outbox(tx, "PassengerOutbox", facts, revision)
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def apply_tick_atomic(
    tick_sim_time: datetime,
    *,
    status_groups: list[dict] | None = None,
    dwell_items: list[tuple[str, int]] | None = None,
    location_updates: list[dict] | None = None,
    risk_updates: list[dict] | None = None,
    facts: list[dict] | None = None,
) -> bool:
    """Per-tick, per-owner atomic advancement of the passenger FSM (G1-a).

    All of a tick's domain writes + fact staging commit in ONE ``execute_write``,
    gated by a locked ``PassengerRuntime {id:'latest', last_tick_sim_time,
    revision}`` checkpoint (the cost-service ``CostRuntime`` / flight-service
    ``FlightRuntime`` mechanism, generalized):

      1. ``MERGE`` + lock ``PassengerRuntime`` (serialises concurrent writers,
         bumps the monotonic ``revision`` used for outbox delivery order).
      2. If ``tick_sim_time <= last_tick_sim_time`` → **return False** (idempotent
         replay / crash-resume: a re-delivered or already-applied tick re-does
         nothing). The checkpoint is durable, so this survives restart.
      3. Bulk-write every FSM transition (status groups + dwell + location + risk).
      4. Stage every domain fact into ``PassengerOutbox`` at the runtime revision.
      5. Advance ``last_tick_sim_time`` to ``tick_sim_time``.

    Returns True if the tick was applied, False on idempotent replay. In-memory
    zone/queue bookkeeping (derived, rebuildable per rule #3) is the caller's to
    update post-commit, and only when this returns True.
    """
    status_groups = status_groups or []
    dwell_items = dwell_items or []
    location_updates = location_updates or []
    risk_updates = risk_updates or []
    facts = facts or []
    for group in status_groups:
        if group["status"] not in _VALID_STATUSES:
            raise ValueError(f"Invalid passenger status: {group['status']!r}")
    sim_str = tick_sim_time.isoformat()
    dwell_rows = [{"id": pid, "dwell": dwell} for pid, dwell in dwell_items]

    async def apply(tx) -> bool:
        result = await tx.run(
            "MATCH (s:PassengerRuntime {id: 'latest'}) "
            "SET s._transaction_lock = true REMOVE s._transaction_lock WITH s "
            "SET s.revision = coalesce(s.revision, 0) + 1 "
            "RETURN s.last_tick_sim_time AS last_tick, s.revision AS revision"
        )
        row = await result.single()
        last_tick = row["last_tick"] if row else None
        revision = row["revision"] if row else 1
        if last_tick is not None:
            try:
                last_dt = datetime.fromisoformat(str(last_tick)).replace(tzinfo=None)
            except (ValueError, TypeError):
                last_dt = None
            if last_dt is not None and tick_sim_time <= last_dt:
                return False  # idempotent replay / crash-resume
        await _write_status_groups(tx, status_groups, sim_str)
        if dwell_rows:
            dwell_result = await tx.run(
                "UNWIND $rows AS r MATCH (p:Passenger {id: r.id}) SET p.dwell_minutes = r.dwell",
                rows=dwell_rows,
            )
            await dwell_result.consume()
        await _write_location_updates(tx, location_updates)
        await _write_risk_updates(tx, risk_updates)
        staged_facts = [*facts, *_outbox.transition_batch_facts(
            "PassengerStatusBatchChanged", tick_sim_time, "passenger-service", {
                "status_groups": status_groups, "dwell_items": dwell_items,
                "location_updates": location_updates, "risk_updates": risk_updates,
            }, grouped_ids={"status_groups": "ids"},
        )]
        await _outbox.stage_outbox(tx, "PassengerOutbox", staged_facts, revision)
        advance = await tx.run(
            "MATCH (s:PassengerRuntime {id: 'latest'}) SET s.last_tick_sim_time = $ts",
            ts=sim_str,
        )
        await advance.consume()
        return True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def rebook_passengers_atomic(
    command_id: str,
    command_type: str,
    passenger_ids: list[str],
    sim_time: datetime,
) -> tuple[str, dict, bool]:
    """Atomic rebook command execution + owner receipt (G1-b).

    ONE ``execute_write`` covers: ``load_receipt_in_tx(command_id)`` (durable
    command dedup) → passenger status writes (``rebooking``) → domain
    ``PassengerStatusChanged`` facts (outbox) → ``save_receipt_in_tx`` → the
    ``CommandExecuted`` / ``CommandRejected`` receipt fact (outbox). On
    redelivery the stored receipt is found and only re-emitted — no passenger is
    re-mutated.

    Returns ``(event_type, payload, mutated)`` where ``event_type`` is
    ``CommandExecuted``/``CommandRejected``, ``payload`` the receipt payload, and
    ``mutated`` True only when this call performed the domain write (False on a
    deduped redelivery).
    """
    from _common.command_store import load_receipt_in_tx, save_receipt_in_tx
    from kafka.producer import (
        build_passenger_status_changed_fact,
        build_command_receipt_fact,
    )

    sim_str = sim_time.isoformat()
    terminal_statuses = ("departed", "arrived", "cancelled", "departed_airport")

    async def apply(tx) -> tuple[str, dict, bool]:
        revision = await next_outbox_revision(tx)

        existing = await load_receipt_in_tx(tx, command_id)
        if existing is not None:
            # Redelivery: re-emit the stored receipt, never re-mutate.
            event_type, payload = existing
            receipt_fact = build_command_receipt_fact(event_type, sim_time, payload)
            await _outbox.stage_outbox(
                tx, "PassengerOutbox",
                [{"id": receipt_fact["event_id"], "document": receipt_fact}],
                revision,
            )
            return event_type, payload, False

        # First execution: read eligible passengers inside the transaction.
        result = await tx.run(
            "UNWIND $ids AS pid MATCH (p:Passenger {id: pid}) "
            "RETURN p.id AS id, p.name AS name, p.status AS status, "
            "p.location_zone AS location_zone, p.flight_id AS flight_id, "
            "p.flight_number AS flight_number",
            ids=passenger_ids,
        )
        pax_rows = [dict(r) async for r in result]

        facts: list[dict] = []
        rebooked = 0
        skipped = len(passenger_ids) - len(pax_rows)  # unknown ids
        move_ids: list[str] = []
        for pax in pax_rows:
            if pax.get("status") in terminal_statuses:
                skipped += 1
                continue
            move_ids.append(pax["id"])
            fact = build_passenger_status_changed_fact(
                passenger_id=pax["id"],
                name=pax.get("name") or "",
                previous_status=pax.get("status") or "",
                new_status="rebooking",
                location_zone=pax.get("location_zone") or "",
                sim_time=sim_time,
                flight_id=pax.get("flight_id"),
                flight_number=pax.get("flight_number"),
            )
            facts.append({"id": fact["event_id"], "document": fact})
            rebooked += 1

        if move_ids:
            write = await tx.run(
                "UNWIND $ids AS pid MATCH (p:Passenger {id: pid}) "
                "SET p.status = 'rebooking', p.rebooking_at = $ts",
                ids=move_ids, ts=sim_str,
            )
            await write.consume()

        if rebooked == 0:
            receipt = (
                "CommandRejected",
                {
                    "command_id": command_id,
                    "command_type": command_type,
                    "reason": f"RebookPassengers: no passengers rebooked ({skipped} skipped)",
                },
            )
        else:
            receipt = (
                "CommandExecuted",
                {
                    "command_id": command_id,
                    "command_type": command_type,
                    "reason": None,
                    "rebooked": rebooked,
                    "skipped": skipped,
                },
            )
        await save_receipt_in_tx(tx, command_id, receipt)
        receipt_fact = build_command_receipt_fact(receipt[0], sim_time, receipt[1])
        facts.append({"id": receipt_fact["event_id"], "document": receipt_fact})
        await _outbox.stage_outbox(tx, "PassengerOutbox", facts, revision)
        return receipt[0], receipt[1], True

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def read_tick_checkpoint() -> datetime | None:
    """Return the durable ``last_tick_sim_time`` checkpoint, or None if unset.

    Lets the tick handler cheaply skip an already-applied/replayed tick before
    doing any compute or in-memory mutation; the authoritative replay guard is
    still the locked check inside :func:`apply_tick_atomic`.
    """
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (s:PassengerRuntime {id: 'latest'}) "
            "RETURN s.last_tick_sim_time AS last_tick"
        )
        row = await result.single()
    if not row or row["last_tick"] is None:
        return None
    try:
        return datetime.fromisoformat(str(row["last_tick"])).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


async def set_passenger_dwell(passenger_id: str, dwell_minutes: int) -> None:
    """Set dwell_minutes on a passenger (sampled once on airside transition)."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.dwell_minutes = $dwell",
            id=passenger_id, dwell=dwell_minutes,
        )


async def bulk_set_dwell(items: list[tuple[str, int]]) -> None:
    """Batch-set dwell_minutes for multiple passengers in one UNWIND query."""
    if not items:
        return
    driver = get_driver()
    rows = [{"id": pid, "dwell": dwell} for pid, dwell in items]
    async with driver.session() as session:
        await session.run(
            """
            UNWIND $rows AS r
            MATCH (p:Passenger {id: r.id})
            SET p.dwell_minutes = r.dwell
            """,
            rows=rows,
        )


async def set_connection_risk(passenger_id: str, risk: str) -> None:
    """Update connection risk level on a passenger node."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.connection_risk = $risk",
            id=passenger_id, risk=risk,
        )


async def update_passenger_location(passenger_id: str, new_zone: str) -> None:
    """Update only location_zone for a passenger without changing status timestamps."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            "MATCH (p:Passenger {id: $id}) SET p.location_zone = $zone",
            id=passenger_id,
            zone=new_zone,
        )


async def get_zone_density() -> dict[str, int]:
    """Get passenger count per location_zone."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)
    WHERE p.location_zone IS NOT NULL
      AND NOT p.status IN ['departed_airport', 'boarded']
    RETURN p.location_zone AS zone, count(p) AS n
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["zone"]: r["n"] for r in records}


async def get_passengers_by_status(status: str, scheduled_before: str | None = None) -> list[dict]:
    """Get all passengers with a given status.

    If scheduled_before is provided (ISO datetime string), only returns passengers
    on flights with scheduled_time <= that value. This dramatically reduces result
    sets for statuses like 'booked' where most passengers are far from their flight.
    """
    driver = get_driver()
    if scheduled_before:
        query = """
        MATCH (p:Passenger {status: $status})-[:ON_FLIGHT]->(f:Flight)
        WHERE f.scheduled_time <= $before
        OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
        RETURN p.id AS id, p.name AS name, f.id AS flight_id,
               p.special_assistance AS special_assistance,
               p.location_zone AS location_zone,
               p.dwell_minutes AS dwell_minutes,
               p.airside_at AS airside_at,
               p.deplaning_at AS deplaning_at,
               p.baggage_claim_at AS baggage_claim_at,
               p.customs_at AS customs_at,
               p.connection AS connection,
               p.connection_flight_id AS connection_flight_id,
               f.flight_number AS flight_number,
               f.estimated_time AS estimated_time,
               f.scheduled_time AS scheduled_time,
               f.status AS flight_status,
               f.direction AS direction,
               f.flight_type AS flight_type,
               g.id AS gate_id,
               g.terminal_id AS terminal_id
        """
        async with driver.session() as session:
            result = await session.run(query, status=status, before=scheduled_before)
            return [dict(r) async for r in result]
    else:
        query = """
        MATCH (p:Passenger {status: $status})-[:ON_FLIGHT]->(f:Flight)
        OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
        RETURN p.id AS id, p.name AS name, f.id AS flight_id,
               p.special_assistance AS special_assistance,
               p.location_zone AS location_zone,
               p.dwell_minutes AS dwell_minutes,
               p.airside_at AS airside_at,
               p.deplaning_at AS deplaning_at,
               p.baggage_claim_at AS baggage_claim_at,
               p.customs_at AS customs_at,
               p.connection AS connection,
               p.connection_flight_id AS connection_flight_id,
               f.flight_number AS flight_number,
               f.estimated_time AS estimated_time,
               f.scheduled_time AS scheduled_time,
               f.status AS flight_status,
               f.direction AS direction,
               f.flight_type AS flight_type,
               g.id AS gate_id,
               g.terminal_id AS terminal_id
        """
        async with driver.session() as session:
            result = await session.run(query, status=status)
            return [dict(r) async for r in result]


async def get_passengers_by_flight(flight_id: str) -> list[dict]:
    """Get all passengers on a specific flight."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight {id: $fid})
    RETURN p.id AS id, p.name AS name, p.status AS status,
           p.location_zone AS location_zone,
           p.special_assistance AS special_assistance,
           p.connection AS connection,
           p.pnr AS pnr
    """
    async with driver.session() as session:
        result = await session.run(query, fid=flight_id)
        return [dict(r) async for r in result]


async def get_connecting_passengers() -> list[dict]:
    """Get all connecting passengers with their flight info."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(f:Flight)
    WHERE NOT p.status IN ['departed_airport', 'boarded', 'missed_connection']
    OPTIONAL MATCH (cf:Flight {id: p.connection_flight_id})
    OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
    OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(ig:Gate)
    OPTIONAL MATCH (cf)-[:ASSIGNED_TO]->(cg:Gate)
    RETURN p.id AS id, p.name AS name, p.pnr AS pnr,
           p.status AS status, p.connection_risk AS connection_risk,
           p.special_assistance AS special_assistance,
           f.flight_number AS inbound_flight,
           f.delay_minutes AS inbound_delay,
           f.estimated_time AS inbound_estimated,
           f.status AS inbound_status,
           ig.id AS inbound_gate_id,
           cf.flight_number AS connection_flight,
           cf.estimated_time AS connection_estimated,
           cf.scheduled_time AS connection_scheduled,
           cg.id AS connection_gate_id,
           count(b) AS baggage_count
    """
    async with driver.session() as session:
        result = await session.run(query)
        return [dict(r) async for r in result]


async def get_departure_flights_in_window(sim_time: datetime, window_min: int = 90) -> list[dict]:
    """Get departure flights within a time window, grouped by terminal."""
    driver = get_driver()
    end_time = sim_time.isoformat()
    from datetime import timedelta
    window_end = (sim_time + timedelta(minutes=window_min)).isoformat()
    query = """
    MATCH (f:Flight)-[:ASSIGNED_TO]->(g:Gate)
    WHERE f.direction = 'departure'
      AND f.status IN ['scheduled', 'boarding', 'delayed']
      AND f.estimated_time >= $start AND f.estimated_time <= $end
    RETURN g.terminal_id AS terminal_id,
           count(f) AS flight_count,
           sum(f.pax_count) AS total_pax
    """
    async with driver.session() as session:
        result = await session.run(query, start=end_time, end=window_end)
        return [dict(r) async for r in result]


async def get_forecast_departures(sim_time: datetime, horizon_minutes: int) -> list[dict]:
    """Read the known schedule once for all future forecast windows."""
    from datetime import timedelta

    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (f:Flight)-[:ASSIGNED_TO]->(g:Gate) "
            "WHERE f.direction = 'departure' "
            "AND f.status IN ['scheduled', 'boarding', 'delayed'] "
            "AND f.estimated_time >= $start AND f.estimated_time <= $end "
            "RETURN DISTINCT f.id AS flight_id, f.estimated_time AS estimated_time, "
            "g.terminal_id AS terminal_id, f.pax_count AS pax_count",
            start=sim_time.isoformat(),
            end=(sim_time + timedelta(minutes=horizon_minutes)).isoformat(),
        )
        return [dict(row) async for row in result]


async def get_status_counts() -> dict[str, int]:
    """Get passenger counts by status."""
    driver = get_driver()
    query = """
    MATCH (p:Passenger)
    RETURN p.status AS status, count(p) AS cnt
    """
    async with driver.session() as session:
        result = await session.run(query)
        records = [record async for record in result]
    return {r["status"]: r["cnt"] for r in records if r["status"]}


async def get_alerts(
    alert_type: str | None = None,
    urgency: str | None = None,
    flight_id: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Get recent alerts from in-memory store (no Neo4j storage for alerts)."""
    # Alerts are stored in-memory and provided via the consumer module
    return []


# ---------------------------------------------------------------------------
# Wheelchair / accessibility (1C)
# ---------------------------------------------------------------------------

async def upsert_wheelchair_resource(
    terminal: str, total_count: int, available_count: int
) -> None:
    """Create or update the WheelchairResource for a terminal."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MERGE (w:WheelchairResource {terminal: $terminal})
            SET w.total_count = $total_count,
                w.available_count = $available_count,
                w.updated_at = $updated_at
            """,
            terminal=terminal,
            total_count=int(total_count),
            available_count=int(available_count),
            updated_at=datetime.utcnow().isoformat(),
        )


async def write_wheelchair_assignment(record: dict) -> None:
    """Persist (or update) a WheelchairAssignment record."""
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            """
            MERGE (a:WheelchairAssignment {id: $id})
            SET a += $props
            WITH a
            OPTIONAL MATCH (p:Passenger {id: $passenger_id})
            FOREACH (_ IN CASE WHEN p IS NULL THEN [] ELSE [1] END |
                MERGE (a)-[:FOR_PASSENGER]->(p)
            )
            """,
            id=record["id"],
            passenger_id=record.get("passenger_id"),
            props={k: v for k, v in record.items() if k != "id" and v is not None},
        )


async def list_recent_assignments(since_iso: str | None = None, limit: int = 5000) -> list[dict]:
    """List WheelchairAssignment records since a given sim-time ISO string."""
    driver = get_driver()
    cypher = (
        "MATCH (a:WheelchairAssignment) "
        + ("WHERE a.requested_at >= $since " if since_iso else "")
        + "RETURN a ORDER BY a.requested_at DESC LIMIT $limit"
    )
    async with driver.session() as session:
        result = await session.run(cypher, since=since_iso, limit=int(limit))
        return [dict(rec["a"]) async for rec in result]


async def save_security_projection(rows: list[dict]) -> None:
    """Public measured aggregates; the tick-scoped driver shares its transaction."""
    async with get_driver().session() as session:
        await (await session.run(
            "UNWIND $rows AS row MERGE (s:SecurityCheckpoint {terminal: row.terminal}) SET s += row",
            rows=rows,
        )).consume()


async def save_security_lanes(terminal: str, lanes: int, sim_time: datetime) -> None:
    """Passenger-service owns operational security lane overrides."""
    async with get_driver().session() as session:
        result = await session.run(
            "MERGE (s:SecurityCheckpoint {terminal: $terminal}) "
            "SET s.lanes_open = $lanes, s.updated_at = $sim_time",
            terminal=terminal, lanes=lanes, sim_time=sim_time.isoformat(),
        )
        await result.consume()


async def load_security_breaches() -> dict[str, str]:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (i:Incident {type: 'security_breach'}) "
            "WHERE i.status IN ['active', 'contained'] "
            "RETURN i.id AS id, i.location AS location"
        )
        return {row["id"]: row["location"] async for row in result}


async def load_security_lanes() -> dict[str, int]:
    async with get_driver().session() as session:
        result = await session.run(
            "MATCH (s:SecurityCheckpoint) RETURN s.terminal AS terminal, s.lanes_open AS lanes"
        )
        return {row["terminal"]: row["lanes"] async for row in result}


async def security_lane_command_atomic(
    command_id: str, command_type: str, terminal: str | None,
    lanes: int | None, sim_time: datetime, rejection: str | None = None,
) -> tuple[str, dict, bool]:
    """Lane override, domain fact and receipt/fact commit together, even on rejection."""
    from _common.command_store import load_receipt_in_tx, save_receipt_in_tx
    from kafka.producer import build_command_receipt_fact
    from uuid import uuid4

    async def apply(tx):
        # Shared ordering lock also serializes lane commands against ticks.
        row = await (await tx.run(
            "MATCH (s:PassengerRuntime {id: 'latest'}) "
            "SET s._transaction_lock = true REMOVE s._transaction_lock WITH s "
            "SET s.revision = coalesce(s.revision, 0) + 1 RETURN s.revision AS revision"
        )).single()
        revision = row["revision"]
        receipt = await load_receipt_in_tx(tx, command_id)
        mutated = receipt is None
        facts = []
        if receipt is None:
            reason = rejection
            if reason is None:
                checkpoint = await (await tx.run(
                    "MERGE (s:SecurityCheckpoint {terminal: $terminal}) "
                    "WITH s, s.lanes_open AS previous "
                    "SET s.lanes_open = $lanes, s.updated_at = $ts "
                    "RETURN previous, properties(s) AS checkpoint",
                    terminal=terminal, lanes=lanes, ts=sim_time.isoformat(),
                )).single()
                document = build_command_receipt_fact("SecurityLanesChanged", sim_time, {
                    "terminal": terminal, "lanes_open": lanes,
                    "previous_lanes_open": checkpoint["previous"],
                })
                facts.append({"id": document["event_id"], "document": document})
                measured = dict(checkpoint.get("checkpoint") or {})
                depth = measured.get("queue_depth", 0)
                wait = 999.0 if measured.get("frozen", False) else round(depth / (lanes * 180) * 60, 1)
                measured.update(terminal=terminal, lanes_open=lanes, queue_depth=depth,
                                wait_minutes=wait, at=sim_time.isoformat(), updated_at=sim_time.isoformat())
                await (await tx.run(
                    "MATCH (s:SecurityCheckpoint {terminal: $terminal}) SET s += $row",
                    terminal=terminal, row=measured,
                )).consume()
                document = build_command_receipt_fact("SecurityQueueUpdated", sim_time, measured)
                facts.append({"id": document["event_id"], "document": document})
            receipt = ("CommandRejected" if reason else "CommandExecuted", {
                "command_id": command_id, "command_type": command_type, "reason": reason,
            })
            await save_receipt_in_tx(tx, command_id, receipt)
        document = build_command_receipt_fact(receipt[0], sim_time, receipt[1])
        # Receipt retries are separate deliveries of the stored outcome.
        document["event_id"] = str(uuid4())
        facts.append({"id": document["event_id"], "document": document})
        await _outbox.stage_outbox(tx, "PassengerOutbox", facts, revision)
        return receipt[0], receipt[1], mutated

    async with get_driver().session() as session:
        return await session.execute_write(apply)


async def next_outbox_revision(tx) -> int:
    row = await (await tx.run(
        "MATCH (s:PassengerRuntime {id: 'latest'}) "
        "SET s._transaction_lock = true REMOVE s._transaction_lock WITH s "
        "SET s.revision = coalesce(s.revision, 0) + 1 "
        "RETURN s.revision AS revision"
    )).single()
    return row["revision"]

"""Debug and development API endpoints for sim-orchestrator.

Provides entity injection, Cypher console, and snapshot management
for the debug panel (Phase 0 developer tooling).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db.neo4j import get_driver
from services import clock
from services.settings import get_settings
from services.snapshot import (
    create_snapshot,
    delete_snapshot,
    list_snapshots,
    restore_snapshot,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/debug")

# ── Cypher validation ────────────────────────────────────────

# Only allow read-only Cypher statements
_READ_ONLY_PATTERN = re.compile(
    r"^\s*(MATCH|RETURN|WITH|UNWIND|OPTIONAL\s+MATCH|CALL|UNION|ORDER|SKIP|LIMIT|WHERE|PROFILE|EXPLAIN)\b",
    re.IGNORECASE,
)

_MUTATION_KEYWORDS = re.compile(
    r"\b(CREATE|DELETE|DETACH|SET|REMOVE|MERGE|DROP|FOREACH)\b",
    re.IGNORECASE,
)


# ── Request models ───────────────────────────────────────────


class CypherRequest(BaseModel):
    query: str = Field(..., min_length=5, max_length=5000)
    params: dict = Field(default_factory=dict)


class PassengerInjectRequest(BaseModel):
    flight_id: str
    count: int = Field(ge=1, le=500)
    status: str = Field(default="checked_in")


class FlightInjectRequest(BaseModel):
    direction: str = Field(default="departure")
    origin: Optional[str] = None
    destination: Optional[str] = None
    airline_code: Optional[str] = None
    aircraft_type: Optional[str] = None
    gate: Optional[str] = None
    departure_time: Optional[str] = None
    seed_passengers: bool = True
    seed_baggage: bool = True


class BaggageInjectRequest(BaseModel):
    flight_id: str
    count: int = Field(ge=1, le=200)
    zone_status: str = Field(default="check_in")


class SnapshotCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)


class SnapshotRestoreRequest(BaseModel):
    filename: str


class SnapshotDeleteRequest(BaseModel):
    filename: str


class EntityUpdateRequest(BaseModel):
    """Update properties of an entity by label and id."""
    label: str
    entity_id: str
    properties: dict


# ── Cypher console ───────────────────────────────────────────


@router.post("/cypher")
async def cypher_console(req: CypherRequest):
    """Execute a read-only Cypher query and return results as a table.

    Only MATCH/RETURN/WITH/CALL queries are allowed. Mutation keywords
    (CREATE, DELETE, SET, MERGE, etc.) are rejected.
    """
    query = req.query.strip()

    if not _READ_ONLY_PATTERN.match(query):
        raise HTTPException(
            status_code=400,
            detail="Only read-only Cypher queries are allowed (MATCH, RETURN, CALL, etc.)",
        )

    if _MUTATION_KEYWORDS.search(query):
        raise HTTPException(
            status_code=400,
            detail="Mutation keywords (CREATE, DELETE, SET, MERGE, REMOVE, DROP) are not allowed",
        )

    try:
        driver = get_driver()
        async with driver.session() as session:
            result = await session.run(query, **req.params)
            keys = list(result.keys())

            rows = []
            async for record in result:
                row = {}
                for key in keys:
                    val = record[key]
                    # Convert Neo4j types to JSON-safe values
                    if hasattr(val, "isoformat"):
                        row[key] = val.isoformat()
                    elif hasattr(val, "__iter__") and not isinstance(val, (str, dict)):
                        row[key] = list(val)
                    else:
                        row[key] = val
                rows.append(row)

            return {
                "columns": keys,
                "rows": rows,
                "row_count": len(rows),
            }
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Cypher error: {e}")


# ── Entity inspector ─────────────────────────────────────────


@router.get("/entity/{label}/{entity_id}")
async def get_entity(label: str, entity_id: str):
    """Fetch a single entity with its relationships for inspection."""
    # Sanitize label to prevent injection
    if not re.match(r"^[A-Za-z_]+$", label):
        raise HTTPException(status_code=400, detail="Invalid label name")

    driver = get_driver()
    async with driver.session() as session:
        # Get node properties
        result = await session.run(
            f"MATCH (n:{label}) WHERE n.id = $id OR n.tag = $id "
            "RETURN properties(n) AS props, labels(n) AS labels",
            id=entity_id,
        )
        record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail=f"{label} {entity_id} not found")

        props = dict(record["props"])
        for k, v in props.items():
            if hasattr(v, "isoformat"):
                props[k] = v.isoformat()

        # Get relationships
        result = await session.run(
            f"MATCH (n:{label})-[r]-(m) WHERE n.id = $id OR n.tag = $id "
            "RETURN type(r) AS rel_type, "
            "       startNode(r) = n AS outgoing, "
            "       labels(m) AS target_labels, "
            "       m.id AS target_id, "
            "       m.name AS target_name, "
            "       properties(r) AS rel_props",
            id=entity_id,
        )
        relationships = []
        async for rec in result:
            rel_props = dict(rec["rel_props"]) if rec["rel_props"] else {}
            for k, v in rel_props.items():
                if hasattr(v, "isoformat"):
                    rel_props[k] = v.isoformat()
            relationships.append({
                "type": rec["rel_type"],
                "direction": "outgoing" if rec["outgoing"] else "incoming",
                "target_labels": list(rec["target_labels"]),
                "target_id": rec["target_id"] or rec["target_name"],
                "properties": rel_props,
            })

        return {
            "labels": list(record["labels"]),
            "properties": props,
            "relationships": relationships,
        }


@router.patch("/entity")
async def update_entity(req: EntityUpdateRequest):
    """Update properties of an entity. Writes to Neo4j and returns updated props.

    This is the write-back for the entity inspector panel.
    """
    label = req.label
    if not re.match(r"^[A-Za-z_]+$", label):
        raise HTTPException(status_code=400, detail="Invalid label name")

    # Only allow updating known safe properties
    forbidden_props = {"id", "tag"}
    update_props = {k: v for k, v in req.properties.items() if k not in forbidden_props}

    if not update_props:
        raise HTTPException(status_code=400, detail="No valid properties to update")

    driver = get_driver()
    async with driver.session() as session:
        # Build SET clause
        set_parts = [f"n.{k} = ${k}" for k in update_props]
        set_clause = ", ".join(set_parts)

        result = await session.run(
            f"MATCH (n:{label}) WHERE n.id = $entity_id OR n.tag = $entity_id "
            f"SET {set_clause} "
            "RETURN properties(n) AS props",
            entity_id=req.entity_id,
            **update_props,
        )
        record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail=f"{label} {req.entity_id} not found")

        props = dict(record["props"])
        for k, v in props.items():
            if hasattr(v, "isoformat"):
                props[k] = v.isoformat()

        return {"updated": True, "properties": props}


# ── Passenger injection ──────────────────────────────────────


@router.post("/inject/passengers")
async def inject_passengers(req: PassengerInjectRequest):
    """Inject N passengers for a given flight directly into Neo4j.

    Passengers are created with the specified status and linked to the
    flight. PassengerStatusChanged events are emitted for each.
    """
    import random
    import string
    from uuid import uuid4
    from kafka.producer import produce_event
    from services.fixtures import get_fixtures

    driver = get_driver()

    # Verify flight exists
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:Flight {id: $fid}) RETURN f.id AS id, f.gate_id AS gate_id, "
            "f.direction AS direction",
            fid=req.flight_id,
        )
        record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail=f"Flight {req.flight_id} not found")

    gate_id = record["gate_id"] or "A01"
    terminal = gate_id[0] if gate_id else "A"

    fixtures = get_fixtures()
    first_names = fixtures["first_names"]
    surnames = fixtures["surnames"]
    rng = random.Random()
    sim_time = clock.get_sim_time()

    # Zone mapping based on status
    zone_map = {
        "booked": None,
        "checked_in": f"check-in-{terminal}",
        "security_queue": f"security-{terminal}",
        "airside": f"airside-{terminal}",
        "at_gate": gate_id,
        "boarding": gate_id,
        "boarded": gate_id,
    }
    zone = zone_map.get(req.status)

    passengers = []
    for _ in range(req.count):
        pid = str(uuid4())
        pnr = "".join(rng.choices(string.ascii_uppercase + string.digits, k=6))
        name = f"{rng.choice(first_names)} {rng.choice(surnames)}"

        passengers.append({
            "id": pid,
            "name": name,
            "pnr": pnr,
            "status": req.status,
            "location_zone": zone,
            "nationality": "XX",
            "seat": f"{rng.randint(1, 40)}{rng.choice('ABCDEF')}",
            "special_assistance": False,
            "connection": False,
        })

    # Write to Neo4j
    async with driver.session() as session:
        await session.run(
            """
            UNWIND $pax AS p
            CREATE (n:Passenger {
                id: p.id,
                name: p.name,
                pnr: p.pnr,
                status: p.status,
                location_zone: p.location_zone,
                nationality: p.nationality,
                seat: p.seat,
                special_assistance: p.special_assistance,
                connection: p.connection,
                created_at: $sim_time
            })
            WITH n, p
            MATCH (f:Flight {id: $flight_id})
            CREATE (n)-[:ON_FLIGHT]->(f)
            """,
            pax=passengers,
            flight_id=req.flight_id,
            sim_time=sim_time.isoformat(),
        )

    # Emit Kafka events
    for pax in passengers:
        produce_event(
            topic="passengers.events",
            event_type="PassengerStatusChanged",
            sim_time=sim_time,
            payload={
                "passenger_id": pax["id"],
                "flight_id": req.flight_id,
                "previous_status": None,
                "new_status": req.status,
                "location_zone": zone,
                "at": sim_time.isoformat(),
            },
            key=pax["id"],
        )

    return {
        "injected": req.count,
        "flight_id": req.flight_id,
        "status": req.status,
        "passenger_ids": [p["id"] for p in passengers],
    }


# ── Flight injection ─────────────────────────────────────────


@router.post("/inject/flight")
async def inject_flight(req: FlightInjectRequest):
    """Create a new flight on the fly with full downstream seeding.

    Optionally generates passengers and baggage for the flight.
    Triggers normal downstream processing (passengers, baggage, turnaround plan).
    """
    import random
    from datetime import datetime
    from uuid import uuid4
    from kafka.producer import produce_event
    from services.fixtures import get_fixtures

    fixtures = get_fixtures()
    rng = random.Random()
    sim_time = clock.get_sim_time()

    # Select airline
    airlines = fixtures["airlines"]
    if req.airline_code:
        airline = next((a for a in airlines if a["code"] == req.airline_code), airlines[0])
    else:
        weights = [a["market_share"] for a in airlines]
        airline = rng.choices(airlines, weights=weights, k=1)[0]

    # Select destination
    destinations = fixtures["destinations"]
    if req.destination:
        dest = next((d for d in destinations if d["iata"] == req.destination), destinations[0])
    else:
        weights = [d["weight"] for d in destinations]
        dest = rng.choices(destinations, weights=weights, k=1)[0]

    # Select aircraft type
    aircraft_types = fixtures["aircraft_types"]
    if req.aircraft_type:
        ac = next((a for a in aircraft_types if a["icao"] == req.aircraft_type), aircraft_types[0])
    else:
        ac = rng.choice(aircraft_types)

    flight_id = str(uuid4())
    flight_number = f"{airline['code']}{rng.randint(100, 999)}"

    # Parse departure time or default to +30min from sim_time
    if req.departure_time:
        dep_time = datetime.fromisoformat(req.departure_time)
    else:
        dep_time = sim_time + __import__("datetime").timedelta(minutes=30)

    gate = req.gate or f"{airline.get('preferred_terminal', 'A')}01"

    from services.airport_config import load_airport_runtime_config
    runtime = load_airport_runtime_config()

    origin = req.origin or runtime.identity.iata
    destination_iata = dest["iata"]

    direction = req.direction
    if direction == "arrival":
        origin, destination_iata = destination_iata, runtime.identity.iata

    flight = {
        "id": flight_id,
        "flight_number": flight_number,
        "direction": direction,
        "airline_code": airline["code"],
        "airline_name": airline["name"],
        "aircraft_type": ac["icao"],
        "aircraft_body": ac.get("body", "narrow"),
        "seat_capacity": ac["seats"],
        "origin": origin,
        "destination": destination_iata,
        "gate_id": gate,
        "runway_id": runtime.departure_runway_ids[0] if direction == "departure" else runtime.arrival_runway_ids[0],
        "status": "scheduled",
        "scheduled_time": dep_time.isoformat(),
        "delay_minutes": 0,
        "flight_type": "domestic",
        "route_category": "short_haul",
    }

    # Write flight to Neo4j
    driver = get_driver()
    async with driver.session() as session:
        await session.run(
            """
            CREATE (f:Flight {
                id: $f.id,
                flight_number: $f.flight_number,
                direction: $f.direction,
                airline_code: $f.airline_code,
                airline_name: $f.airline_name,
                aircraft_type: $f.aircraft_type,
                aircraft_body: $f.aircraft_body,
                seat_capacity: $f.seat_capacity,
                origin: $f.origin,
                destination: $f.destination,
                gate_id: $f.gate_id,
                runway_id: $f.runway_id,
                status: $f.status,
                scheduled_time: $f.scheduled_time,
                delay_minutes: $f.delay_minutes,
                flight_type: $f.flight_type,
                route_category: $f.route_category
            })
            WITH f
            OPTIONAL MATCH (g:Gate {id: $f.gate_id})
            FOREACH (_ IN CASE WHEN g IS NOT NULL THEN [1] ELSE [] END |
                CREATE (f)-[:ASSIGNED_TO]->(g)
            )
            """,
            f=flight,
        )

    # Emit FlightScheduleSeeded event
    produce_event(
        topic="flights.schedule",
        event_type="FlightScheduleSeeded",
        sim_time=sim_time,
        payload={
            "sim_day": clock.get_sim_day(),
            "sim_date": sim_time.date().isoformat(),
            "total_flights": 1,
            "flight_ids": [flight_id],
        },
    )

    pax_count = 0
    bag_count = 0

    if req.seed_passengers:
        from services.passengers import generate_passengers
        pax_count, pax_list = await generate_passengers(
            flights=[flight], seed=None, initial_status="booked"
        )

        if req.seed_baggage and pax_list:
            from services.baggage import generate_baggage
            bag_count, _ = await generate_baggage(passengers=pax_list, seed=None)

    return {
        "flight_id": flight_id,
        "flight_number": flight_number,
        "direction": direction,
        "gate": gate,
        "scheduled_time": dep_time.isoformat(),
        "passengers_generated": pax_count,
        "baggage_generated": bag_count,
    }


# ── Baggage injection ────────────────────────────────────────


@router.post("/inject/baggage")
async def inject_baggage(req: BaggageInjectRequest):
    """Inject N baggage items for a given flight at a specific conveyor zone status."""
    import random
    from uuid import uuid4
    from kafka.producer import produce_event

    driver = get_driver()
    sim_time = clock.get_sim_time()
    rng = random.Random()

    # Verify flight exists
    async with driver.session() as session:
        result = await session.run(
            "MATCH (f:Flight {id: $fid}) RETURN f.id AS id, f.gate_id AS gate_id",
            fid=req.flight_id,
        )
        record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail=f"Flight {req.flight_id} not found")

    gate_id = record["gate_id"] or "A01"
    terminal = gate_id[0] if gate_id else "A"

    # Zone mapping
    zone_map = {
        "check_in": f"induction-{terminal}",
        "induction": f"induction-{terminal}",
        "screening": f"screening-unit-{rng.randint(1, 6)}",
        "sorting": "sorting-matrix",
        "make_up": f"make-up-{terminal}-{rng.randint(1, 5)}",
        "loaded": "loaded",
    }
    scan_zone = zone_map.get(req.zone_status, f"induction-{terminal}")

    baggage_items = []
    tag_base = int(sim_time.timestamp()) % 1_000_000_000
    for i in range(req.count):
        bag_id = str(uuid4())
        tag = f"{tag_base + i:010d}"
        weight = round(rng.uniform(5.0, 30.0), 1)

        baggage_items.append({
            "id": bag_id,
            "tag": tag,
            "status": req.zone_status,
            "weight_kg": weight,
            "dg_class": None,
            "flagged": False,
            "scan_zone": scan_zone,
        })

    # Write to Neo4j
    async with driver.session() as session:
        await session.run(
            """
            UNWIND $bags AS b
            CREATE (n:Baggage {
                id: b.id,
                tag: b.tag,
                status: b.status,
                weight_kg: b.weight_kg,
                dg_class: b.dg_class,
                flagged: b.flagged,
                created_at: $sim_time
            })
            WITH n, b
            MATCH (f:Flight {id: $flight_id})
            CREATE (n)-[:LOADED_ON]->(f)
            """,
            bags=baggage_items,
            flight_id=req.flight_id,
            sim_time=sim_time.isoformat(),
        )

    # Emit Kafka events
    for bag in baggage_items:
        produce_event(
            topic="baggage.events",
            event_type="BaggageStatusChanged",
            sim_time=sim_time,
            payload={
                "baggage_id": bag["id"],
                "tag": bag["tag"],
                "flight_id": req.flight_id,
                "previous_status": None,
                "new_status": req.zone_status,
                "scan_zone": scan_zone,
                "at": sim_time.isoformat(),
            },
            key=bag["id"],
        )

    return {
        "injected": req.count,
        "flight_id": req.flight_id,
        "zone_status": req.zone_status,
        "baggage_ids": [b["id"] for b in baggage_items],
    }


# ── Snapshots ────────────────────────────────────────────────


@router.post("/snapshot")
async def create_snapshot_endpoint(req: SnapshotCreateRequest):
    """Create a snapshot of the current simulation state."""
    was_paused = clock.is_paused()
    if not was_paused:
        clock.pause()

    try:
        settings = get_settings().model_dump()
        result = await create_snapshot(
            name=req.name,
            sim_time=clock.get_sim_time(),
            day_number=clock.get_sim_day(),
            tick_number=clock.get_tick_number(),
            speed_multiplier=clock.get_speed(),
            settings=settings,
        )
        return result
    finally:
        if not was_paused:
            clock.resume()


@router.get("/snapshots")
async def list_snapshots_endpoint():
    """List all available snapshots."""
    snapshots = await list_snapshots()
    return {"snapshots": snapshots, "count": len(snapshots)}


@router.post("/snapshot/restore")
async def restore_snapshot_endpoint(req: SnapshotRestoreRequest):
    """Restore the simulation from a snapshot file."""
    clock.pause()

    try:
        result = await restore_snapshot(req.filename)

        # Restore clock state
        from datetime import datetime as dt
        restored_time = dt.fromisoformat(result["sim_time"])
        clock.restore_state(
            sim_time=restored_time,
            day_number=result["day_number"],
            tick_number=result["tick_number"],
            speed_multiplier=result["speed_multiplier"],
        )

        # Restore settings
        if result.get("settings"):
            from services.settings import update_settings
            update_settings(result["settings"])

        # Emit a SnapshotRestored event so all services rebuild in-memory state
        from kafka.producer import produce_event
        produce_event(
            topic="sim.clock",
            event_type="SnapshotRestored",
            sim_time=restored_time,
            payload={
                "snapshot_name": result["name"],
                "sim_time": result["sim_time"],
                "day_number": result["day_number"],
            },
        )

        clock.resume()
        return {
            "restored": True,
            **result,
        }
    except FileNotFoundError as e:
        clock.resume()
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        clock.resume()
        logger.error("Snapshot restore failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Restore failed: {e}")


@router.delete("/snapshot")
async def delete_snapshot_endpoint(req: SnapshotDeleteRequest):
    """Delete a snapshot file."""
    deleted = await delete_snapshot(req.filename)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Snapshot not found: {req.filename}")
    return {"deleted": True, "filename": req.filename}

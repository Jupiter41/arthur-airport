# SKILL — Neo4j & Cypher
## Graph schema · Query patterns · Gotchas

---

## Node labels and key properties

| Label | Key property | Unique constraint |
|---|---|---|
| `Airport` | `icao` | yes |
| `Terminal` | `id` (e.g. `"T-A"`) | yes |
| `Gate` | `id` (e.g. `"B07"`) | yes |
| `Runway` | `id` (e.g. `"09L"`) | yes |
| `Flight` | `id` (UUID) | yes — also index on `flight_number`, `status` |
| `Passenger` | `id` (UUID) | yes — also index on `pnr` |
| `Baggage` | `tag` (10-digit string) | yes — also index on `status` |
| `WeatherState` | `id` (UUID) | yes |
| `Incident` | `id` (UUID) | yes — also index on `type`, `status` |

Full schema → `docs/architecture/DATA_MODEL.md`

---

## Initialisation: constraints and indexes

Run once on service startup (idempotent — `IF NOT EXISTS` is safe to re-run):

```cypher
CREATE CONSTRAINT flight_id IF NOT EXISTS FOR (f:Flight) REQUIRE f.id IS UNIQUE;
CREATE CONSTRAINT passenger_id IF NOT EXISTS FOR (p:Passenger) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT baggage_tag IF NOT EXISTS FOR (b:Baggage) REQUIRE b.tag IS UNIQUE;
CREATE CONSTRAINT gate_id IF NOT EXISTS FOR (g:Gate) REQUIRE g.id IS UNIQUE;
CREATE CONSTRAINT runway_id IF NOT EXISTS FOR (r:Runway) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE;

CREATE INDEX flight_number IF NOT EXISTS FOR (f:Flight) ON (f.flight_number);
CREATE INDEX flight_status  IF NOT EXISTS FOR (f:Flight) ON (f.status);
CREATE INDEX passenger_pnr  IF NOT EXISTS FOR (p:Passenger) ON (p.pnr);
CREATE INDEX baggage_status IF NOT EXISTS FOR (b:Baggage) ON (b.status);
CREATE INDEX incident_type  IF NOT EXISTS FOR (i:Incident) ON (i.type);
CREATE INDEX incident_status IF NOT EXISTS FOR (i:Incident) ON (i.status);
```

---

## Relationship catalogue

```
(Airport)-[:HAS_TERMINAL]->(Terminal)
(Terminal)-[:HAS_GATE]->(Gate)
(Airport)-[:HAS_RUNWAY]->(Runway)
(Flight)-[:ASSIGNED_TO {assigned_at}]->(Gate)
(Flight)-[:USES_RUNWAY {operation, at}]->(Runway)
(Passenger)-[:ON_FLIGHT {seat, boarded_at}]->(Flight)
(Passenger)-[:CARRIES {checked_in_at}]->(Baggage)
(Baggage)-[:LOADED_ON {loaded_at}]->(Flight)
(Incident)-[:AFFECTS {impact}]->(Flight|Gate|Runway)
(Incident)-[:SPAWNED {reason, at}]->(Incident)
(Airport)-[:CURRENT_WEATHER]->(WeatherState)
(WeatherState)-[:PREVIOUS_WEATHER]->(WeatherState)
```

---

## Common query patterns

### Create a node

```cypher
CREATE (f:Flight {
  id: $id,
  flight_number: $flight_number,
  status: 'scheduled',
  direction: $direction,
  airline_code: $airline_code,
  scheduled_time: $scheduled_time,
  estimated_time: $scheduled_time,
  delay_minutes: 0,
  pax_count: $pax_count,
  seat_capacity: $seat_capacity,
  created_at: $created_at
})
RETURN f
```

### Update a node property

```cypher
MATCH (f:Flight {id: $id})
SET f.status = $status,
    f.delay_minutes = $delay_minutes,
    f.estimated_time = $estimated_time
RETURN f
```

### Create a relationship

```cypher
MATCH (f:Flight {id: $flight_id})
MATCH (g:Gate {id: $gate_id})
MERGE (f)-[r:ASSIGNED_TO]->(g)
SET r.assigned_at = $assigned_at
```

### Delete a relationship

```cypher
MATCH (f:Flight {id: $flight_id})-[r:ASSIGNED_TO]->(:Gate)
DELETE r
```

### Get flight with gate and runway

```cypher
MATCH (f:Flight {id: $id})
OPTIONAL MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
OPTIONAL MATCH (f)-[:USES_RUNWAY]->(r:Runway)
RETURN f, g, r
```

### Get all passengers on a flight with their baggage

```cypher
MATCH (p:Passenger)-[:ON_FLIGHT]->(f:Flight {id: $flight_id})
OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
RETURN p, collect(b) AS baggage
ORDER BY p.name
```

### Find at-risk connecting passengers

```cypher
MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(f:Flight)
WHERE f.status IN ['delayed', 'cancelled']
  AND f.delay_minutes > 30
WITH p, f
MATCH (p)-[:ON_FLIGHT]->(cf:Flight)
WHERE cf.id = p.connection_flight_id
RETURN p.name, p.pnr, f.flight_number AS delayed_flight,
       cf.flight_number AS connection_flight,
       f.delay_minutes AS delay_minutes
ORDER BY f.delay_minutes DESC
```

### Get full cascade tree for an incident

```cypher
MATCH path = (root:Incident {id: $incident_id})-[:SPAWNED*0..5]->(child:Incident)
RETURN path
ORDER BY length(path)
```

### Get all flights affected by current weather

```cypher
MATCH (a:Airport)-[:CURRENT_WEATHER]->(w:WeatherState)
WHERE w.runway_impact <> 'none'
MATCH (f:Flight)-[:USES_RUNWAY]->(r:Runway)
WHERE f.status IN ['scheduled', 'boarding', 'approach']
RETURN f.flight_number, f.status, f.estimated_time,
       w.category AS weather, w.runway_impact
ORDER BY f.estimated_time ASC
```

### Update current weather (chain pattern)

```cypher
// Create new weather state
CREATE (w:WeatherState {
  id: $new_id,
  category: $category,
  timestamp: $timestamp,
  visibility_m: $visibility_m,
  wind_speed_kt: $wind_speed_kt
})

// Link to previous
WITH w
MATCH (a:Airport)-[cw:CURRENT_WEATHER]->(old:WeatherState)
CREATE (w)-[:PREVIOUS_WEATHER]->(old)
DELETE cw
CREATE (a)-[:CURRENT_WEATHER]->(w)
```

### Count passengers by zone (for heatmap)

```cypher
MATCH (p:Passenger)
WHERE p.status IN ['security_queue', 'airside', 'at_gate']
RETURN p.location_zone AS zone, count(p) AS density
ORDER BY density DESC
```

---

## Batch operations (seeding)

Use `UNWIND` for bulk inserts — much faster than individual `CREATE` statements:

```cypher
UNWIND $flights AS f
CREATE (:Flight {
  id: f.id,
  flight_number: f.flight_number,
  status: 'scheduled',
  direction: f.direction,
  scheduled_time: f.scheduled_time,
  pax_count: f.pax_count
})
```

Call this with a list of 200+ flight dicts in a single session.run() call.

---

## Gotchas

- **Property values must be primitives or lists of primitives.** You cannot store a dict or nested object as a property. Flatten it or store as JSON string.
- **`MERGE` is not `CREATE OR UPDATE`.** `MERGE` matches the entire pattern — if any property differs, it creates a new node. For upsert, use `MERGE` on key only then `SET` for other properties.
- **Datetimes must be stored as ISO strings** (not Python datetime objects) unless you use the Neo4j temporal type explicitly. Store as `f.scheduled_time = $dt.isoformat()`, retrieve and parse back with `datetime.fromisoformat(record["scheduled_time"])`.
- **`OPTIONAL MATCH` after a `MATCH` applies to the whole row.** If the first `MATCH` returns 3 rows and `OPTIONAL MATCH` finds nothing for 2 of them, those rows get `null` for the optional variable — they are not dropped.
- **`collect()` always returns a list, never null.** Safe to use even if no elements exist — returns `[]`.
- **Session scope:** open a new session per request. Do not share sessions across requests.

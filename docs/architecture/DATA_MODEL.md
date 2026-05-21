# Data model — Neo4j graph schema

**Project:** Arthur International Airport Digital Twin  
**Database:** Neo4j 5.x  
**Query language:** Cypher

---

## 1. Design philosophy

The airport is modelled as a directed property graph. Physical objects (planes, passengers, baggage) are **nodes**. Operational relationships between them (assignment, ownership, traversal) are **edges**. State (flight status, passenger location, weather condition) lives as **properties** on nodes and edges.

The graph lets us answer complex operational questions in a single query that would require multi-table joins in a relational model. Examples:

- *"Which passengers are currently airside and whose connecting flight is at risk?"*
- *"What baggage is loaded on a flight that has been held due to a runway incursion?"*
- *"Which gates are blocked because of a cascading delay originating from weather on runway 09L?"*

---

## 2. Node catalogue

### `Airport`
The singleton root node. All terminals, runways, and infrastructure belong to this node.

| Property | Type | Description |
|---|---|---|
| `iata` | String | `"ART"` |
| `icao` | String | `"KART"` |
| `name` | String | `"Arthur International Airport"` |
| `timezone` | String | `"America/Arthur"` (fictional) |
| `total_gates` | Integer | 42 |
| `created_at` | DateTime | seed timestamp |

---

### `Terminal`
One of three terminals (A, B, C).

| Property | Type | Description |
|---|---|---|
| `id` | String | `"T-A"`, `"T-B"`, `"T-C"` |
| `name` | String | `"Terminal A"` etc. |
| `gate_count` | Integer | 14 |
| `open` | Boolean | operational status |

---

### `Gate`
An individual boarding gate. 42 total (A01–A14, B01–B14, C01–C14).

| Property | Type | Description |
|---|---|---|
| `id` | String | `"A01"` … `"C14"` |
| `terminal_id` | String | FK-style reference |
| `status` | Enum | `available` · `occupied` · `maintenance` · `closed` |
| `pier` | String | `"A"`, `"B"`, `"C"` |
| `jetbridge` | Boolean | has jetbridge |
| `last_assigned_at` | DateTime | last flight assignment |

---

### `Runway`
One of two runways.

| Property | Type | Description |
|---|---|---|
| `id` | String | `"09L"`, `"27R"`, `"09R"`, `"27L"` |
| `length_m` | Integer | runway length in metres |
| `status` | Enum | `open` · `closed` · `restricted` · `incident` |
| `surface` | String | `"asphalt"` |
| `ils` | Boolean | instrument landing system available |
| `current_use` | Enum | `landing` · `takeoff` · `idle` |

---

### `Flight`
A single flight movement (arrival or departure). Each physical flight has two nodes: one for the arrival leg and one for the departure leg.

| Property | Type | Description |
|---|---|---|
| `id` | String | UUID |
| `flight_number` | String | e.g. `"AX412"` |
| `airline_code` | String | 2-letter fictional IATA code |
| `direction` | Enum | `arrival` · `departure` |
| `status` | Enum | `scheduled` · `boarding` · `departed` · `airborne` · `approach` · `landed` · `taxiing` · `at_gate` · `delayed` · `cancelled` · `diverted` |
| `aircraft_type` | String | e.g. `"B738"`, `"A320"` |
| `aircraft_registration` | String | e.g. `"ART-001"` |
| `origin_iata` | String | origin airport (fictional) |
| `destination_iata` | String | destination airport (fictional) |
| `scheduled_time` | DateTime | original STA/STD |
| `estimated_time` | DateTime | current ETA/ETD (updated dynamically) |
| `actual_time` | DateTime | actual ATA/ATD (set on event) |
| `delay_minutes` | Integer | cumulative delay |
| `delay_reason` | String | free-text reason code |
| `pax_count` | Integer | booked passenger count |
| `seat_capacity` | Integer | aircraft seat capacity |

---

### `Passenger`

| Property | Type | Description |
|---|---|---|
| `id` | String | UUID |
| `name` | String | generated fake name |
| `pnr` | String | booking reference (6-char fake) |
| `nationality` | String | ISO 3166-1 alpha-2 |
| `status` | Enum | `checked_in` · `security_queue` · `airside` · `at_gate` · `boarded` · `deplaning` · `baggage_claim` · `departed_airport` |
| `location_zone` | String | current zone: `"check-in"`, `"security"`, `"gate-B07"`, etc. |
| `seat` | String | e.g. `"23A"` |
| `special_assistance` | Boolean | requires assistance |
| `connection` | Boolean | has a connecting flight |
| `connection_flight_id` | String | if `connection=true` |
| `checked_in_at` | DateTime | |
| `boarded_at` | DateTime | |

---

### `Baggage`

| Property | Type | Description |
|---|---|---|
| `id` | String | UUID |
| `tag` | String | 10-digit barcode e.g. `"0074123456"` |
| `weight_kg` | Float | |
| `status` | Enum | `dropped_off` · `inducted` · `screening` · `sorting` · `loaded` · `in_hold` · `arrived` · `on_carousel` · `collected` · `lost` · `flagged` |
| `is_dangerous_goods` | Boolean | DG flag |
| `dg_class` | String | IATA DG class if flagged |
| `carousel` | Integer | arrival carousel number (1–6) |
| `last_scan_zone` | String | last RFID/barcode scan location |
| `last_scan_at` | DateTime | |

---

### `WeatherState`
A snapshot of current weather conditions at KART. One active node at any time; history retained as a chain.

| Property | Type | Description |
|---|---|---|
| `id` | String | UUID |
| `timestamp` | DateTime | when this state became active |
| `category` | Enum | `CAVOK` · `VMC` · `IMC` · `LIFR` |
| `visibility_m` | Integer | visibility in metres |
| `wind_direction` | Integer | degrees |
| `wind_speed_kt` | Integer | knots |
| `wind_gust_kt` | Integer | gusts (0 if none) |
| `ceiling_ft` | Integer | cloud ceiling in feet |
| `temperature_c` | Float | |
| `dew_point_c` | Float | |
| `qnh_hpa` | Integer | altimeter setting |
| `phenomena` | List[String] | e.g. `["TS", "FG", "SN"]` |
| `runway_impact` | Enum | `none` · `reduced_rate` · `single_runway` · `closed` |

---

### `Incident`

| Property | Type | Description |
|---|---|---|
| `id` | String | UUID |
| `type` | Enum | `runway_incursion` · `baggage_fire` · `security_breach` · `severe_weather` · `system_failure` |
| `severity` | Enum | `low` · `medium` · `high` · `critical` |
| `status` | Enum | `active` · `contained` · `resolved` · `escalated` |
| `trigger` | Enum | `manual` · `probabilistic` |
| `title` | String | short human-readable label |
| `description` | String | |
| `location` | String | zone/gate/runway where incident occurred |
| `started_at` | DateTime | |
| `resolved_at` | DateTime | null if active |
| `affected_entity_ids` | List[String] | IDs of impacted flights/gates/etc. |
| `cascade_events` | List[String] | IDs of child incidents/alerts spawned |
| `protocol` | String | emergency protocol triggered |

---

### `CostRecord`
One record per cost or revenue event. Written by cost-service.

| Property | Type | Description |
|---|---|---|
| `id` | String (UUID) | unique |
| `category` | Enum | `landing_fee`, `gate_fee`, `passenger_fee`, `eu261_compensation`, `crew_overtime`, `holding_fuel`, `ground_handling`, `incident_direct`, `incident_response`, `staffing`, `retail_revenue`, `slot_revenue` |
| `amount_eur` | Float | cost or revenue amount (always positive) |
| `currency` | String | `"EUR"` |
| `sim_time` | String (ISO) | when the cost was incurred |
| `sim_day` | Integer | day number in simulation |
| `description` | String | human-readable label |
| `is_revenue` | Boolean | true for revenue records |

---

## 3. Relationship catalogue

| Relationship | From → To | Properties | Description |
|---|---|---|---|
| `HAS_TERMINAL` | Airport → Terminal | — | airport owns terminal |
| `HAS_GATE` | Terminal → Gate | — | terminal owns gate |
| `HAS_RUNWAY` | Airport → Runway | — | airport owns runway |
| `ASSIGNED_TO` | Flight → Gate | `assigned_at: DateTime` | flight assigned to gate |
| `USES_RUNWAY` | Flight → Runway | `operation: "landing"/"takeoff"`, `at: DateTime` | runway usage event |
| `ON_FLIGHT` | Passenger → Flight | `seat: String`, `boarded_at: DateTime` | passenger booked on flight |
| `CARRIES` | Passenger → Baggage | `checked_in_at: DateTime` | passenger owns baggage |
| `LOADED_ON` | Baggage → Flight | `loaded_at: DateTime` | baggage in flight hold |
| `AFFECTS` | Incident → Flight | `impact: String` | incident impacts flight |
| `AFFECTS` | Incident → Gate | `impact: String` | incident impacts gate |
| `AFFECTS` | Incident → Runway | `impact: String` | incident impacts runway |
| `SPAWNED` | Incident → Incident | `reason: String`, `at: DateTime` | cascade: parent spawned child |
| `CURRENT_WEATHER` | Airport → WeatherState | — | active weather snapshot |
| `PREVIOUS_WEATHER` | WeatherState → WeatherState | — | weather history chain |
| `FOR_FLIGHT` | CostRecord → Flight | — | cost linked to a specific flight |
| `FOR_TERMINAL` | CostRecord → Terminal | — | cost linked to a terminal |
| `CAUSED_BY` | CostRecord → Incident | — | cost caused by an incident |
| `FOR_DAY` | CostRecord → Airport | `day: Integer` | daily cost rollup |

---

## 4. Key Cypher query patterns

### Find all at-risk connecting passengers
```cypher
MATCH (p:Passenger {connection: true})-[:ON_FLIGHT]->(f:Flight)
WHERE f.status IN ['delayed', 'cancelled']
  AND f.delay_minutes > 30
MATCH (p)-[:ON_FLIGHT]->(cf:Flight {id: p.connection_flight_id})
RETURN p.name, p.pnr, f.flight_number AS delayed_flight,
       cf.flight_number AS connection, f.delay_minutes AS delay
ORDER BY f.delay_minutes DESC
```

### Find all baggage on a delayed or cancelled flight
```cypher
MATCH (b:Baggage)-[:LOADED_ON]->(f:Flight)
WHERE f.status IN ['delayed', 'cancelled']
RETURN b.tag, b.status, f.flight_number, f.delay_minutes
```

### Find cascade chain from an incident
```cypher
MATCH path = (i:Incident {id: $incident_id})-[:SPAWNED*1..5]->(child:Incident)
RETURN path
```

### Find all flights affected by current weather
```cypher
MATCH (a:Airport)-[:CURRENT_WEATHER]->(w:WeatherState)
WHERE w.runway_impact <> 'none'
MATCH (f:Flight)-[:USES_RUNWAY]->(r:Runway)
WHERE f.status IN ['scheduled', 'boarding', 'approach']
RETURN f.flight_number, f.status, f.estimated_time, w.category, w.runway_impact
ORDER BY f.estimated_time ASC
```

### Get full passenger journey
```cypher
MATCH (p:Passenger {pnr: $pnr})
MATCH (p)-[r:ON_FLIGHT]->(f:Flight)
MATCH (f)-[:ASSIGNED_TO]->(g:Gate)
OPTIONAL MATCH (p)-[:CARRIES]->(b:Baggage)
RETURN p, f, g, collect(b) AS baggage
```

---

## 5. Index and constraint definitions

```cypher
// Uniqueness constraints
CREATE CONSTRAINT flight_id IF NOT EXISTS FOR (f:Flight) REQUIRE f.id IS UNIQUE;
CREATE CONSTRAINT passenger_id IF NOT EXISTS FOR (p:Passenger) REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT baggage_tag IF NOT EXISTS FOR (b:Baggage) REQUIRE b.tag IS UNIQUE;
CREATE CONSTRAINT gate_id IF NOT EXISTS FOR (g:Gate) REQUIRE g.id IS UNIQUE;
CREATE CONSTRAINT runway_id IF NOT EXISTS FOR (r:Runway) REQUIRE r.id IS UNIQUE;
CREATE CONSTRAINT incident_id IF NOT EXISTS FOR (i:Incident) REQUIRE i.id IS UNIQUE;
CREATE CONSTRAINT cost_record_id IF NOT EXISTS FOR (c:CostRecord) REQUIRE c.id IS UNIQUE;

// Lookup indexes
CREATE INDEX flight_number IF NOT EXISTS FOR (f:Flight) ON (f.flight_number);
CREATE INDEX flight_status IF NOT EXISTS FOR (f:Flight) ON (f.status);
CREATE INDEX flight_scheduled IF NOT EXISTS FOR (f:Flight) ON (f.scheduled_time);
CREATE INDEX flight_direction IF NOT EXISTS FOR (f:Flight) ON (f.direction);
CREATE INDEX passenger_pnr IF NOT EXISTS FOR (p:Passenger) ON (p.pnr);
CREATE INDEX passenger_status IF NOT EXISTS FOR (p:Passenger) ON (p.status);
CREATE INDEX passenger_location IF NOT EXISTS FOR (p:Passenger) ON (p.location_zone);
CREATE INDEX passenger_flight IF NOT EXISTS FOR (p:Passenger) ON (p.flight_id);
CREATE INDEX baggage_status IF NOT EXISTS FOR (b:Baggage) ON (b.status);
CREATE INDEX incident_type IF NOT EXISTS FOR (i:Incident) ON (i.type);
CREATE INDEX incident_status IF NOT EXISTS FOR (i:Incident) ON (i.status);
CREATE INDEX cost_record_category IF NOT EXISTS FOR (c:CostRecord) ON (c.category);
CREATE INDEX cost_record_sim_day IF NOT EXISTS FOR (c:CostRecord) ON (c.sim_day);
```

---

## 6. SpacetimeDB alternative model (optional)

If SpacetimeDB is used as the real-time entity layer, the above nodes map to **tables** and relationships map to **foreign keys**. The key difference is that SpacetimeDB tables support **client subscriptions** natively — dashboards subscribe to a SQL-like filter and receive push updates automatically without Kafka fan-out.

```rust
// Example SpacetimeDB table definition (Rust reducer)
#[spacetimedb(table)]
pub struct Flight {
    #[primarykey]
    pub id: String,
    pub flight_number: String,
    pub status: String,
    pub gate_id: Option<String>,
    pub delay_minutes: i32,
    pub estimated_time: Timestamp,
}
```

The SpacetimeDB path is documented as an option but the reference implementation uses Neo4j.

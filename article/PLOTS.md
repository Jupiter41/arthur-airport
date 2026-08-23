# Architecture plots

This document collects Mermaid diagrams for the Arthur International Airport
digital twin. The diagrams are derived from the architecture, simulation,
event-bus, data-model, and service specifications in `docs/`.

## 1. System architecture

The API gateway is the only synchronous entry point for dashboard clients.
Domain services communicate asynchronously through Kafka and persist their
authoritative entities in Neo4j. Prometheus and Grafana observe the runtime.

```mermaid
flowchart TB
    client[React dashboard]
    gateway[API gateway\nNode.js / Express\n:3000]
    kafka[(Apache Kafka\nevent bus)]
    neo[(Neo4j\nentity graph)]
    metrics[Prometheus + Grafana\nmetrics and dashboards]

    subgraph services[Airport domain services]
        flight[Flight service\n:8001]
        pax[Passenger service\n:8002]
        bag[Baggage service\n:8003]
        weather[Weather service\n:8004]
        incident[Incident service\n:8005]
        sim[Simulation orchestrator\n:8006]
        analysis[Analysis service\n:8007]
        cost[Cost service\n:8008]
    end

    client -->|REST aggregate and queries| gateway
    client <-->|WebSocket event stream| gateway
    gateway -->|REST only| flight
    gateway -->|REST only| pax
    gateway -->|REST only| bag
    gateway -->|REST only| weather
    gateway -->|REST only| incident
    gateway -->|REST only| sim
    gateway -->|REST only| analysis
    gateway -->|REST only| cost

    services <--> |publish and consume facts| kafka
    services -->|read and write domain state| neo
    kafka -->|all topics consumed by gateway| gateway
    services -.->|/metrics, /health, /ready| metrics
```

## 2. Event-driven communication

Kafka topics are domain-scoped. Producers publish state-change facts, while
each consumer independently updates its own view or forwards events to the
dashboard. The clock topic is broadcast to every service.

```mermaid
flowchart LR
    sim[sim-orchestrator]
    flight[flight-service]
    pax[passenger-service]
    bag[baggage-service]
    weather[weather-service]
    incident[incident-service]
    cost[cost-service]
    analysis[analysis-service]
    gateway[api-gateway]

    clock((sim.clock))
    fe((flights.events))
    fs((flights.schedule))
    pe((passengers.events))
    be((baggage.events))
    we((weather.events))
    ie((incidents.events))
    ia((incidents.alerts))
    inject((incidents.inject))
    ce((cost.events))
    ae((analysis.events))

    sim --> clock
    clock --> flight
    clock --> pax
    clock --> bag
    clock --> weather
    clock --> incident
    clock --> cost
    clock --> analysis

    sim --> fs --> flight
    flight --> fe
    fe --> pax
    fe --> bag
    fe --> incident
    fe --> cost
    fe --> gateway
    pax --> pe
    pe --> incident
    pe --> cost
    pe --> gateway
    bag --> be
    be --> cost
    be --> gateway
    weather --> we
    we --> flight
    we --> incident
    we --> gateway
    incident --> ie
    ie --> flight
    ie --> pax
    ie --> bag
    ie --> cost
    ie --> gateway
    incident --> ia --> gateway
    gateway --> inject --> incident
    cost --> ce --> gateway
    analysis --> ae --> gateway
```

## 3. Simulation clock and daily loop

The orchestrator is a conductor rather than an owner of domain state. It
advances virtual time, seeds the next day at the boundary, and lets services
react to the same `SimClockTick` stream.

```mermaid
sequenceDiagram
    participant O as sim-orchestrator
    participant K as Kafka: sim.clock
    participant F as flight-service
    participant P as passenger-service
    participant W as weather-service
    participant I as incident-service
    participant G as API gateway
    participant D as Dashboard

    O->>O: Advance sim_time by configured speed
    O->>K: SimClockTick(sim_time, speed_multiplier)
    par Domain reactions
        K-->>F: Wake flight state machines
        K-->>P: Advance passenger queues
        K-->>W: Evaluate weather FSM
        K-->>I: Evaluate probabilistic incidents
    end
    F->>K: FlightStatusChanged, if state changed
    W->>K: WeatherStateChanged, if weather changed
    I->>K: IncidentCreated or IncidentAlert, if triggered
    K-->>G: Consume domain events
    G-->>D: Push WebSocket updates
    O->>O: At day boundary, seed next schedule
    O->>K: FlightScheduleSeeded
```

## 4. Flight lifecycle

Flight transitions are driven by simulated time and constrained by weather,
incidents, runway capacity, gates, and boarding progress.

```mermaid
stateDiagram-v2
    [*] --> scheduled
    scheduled --> boarding: T-60 min / gate available
    boarding --> departed: T-0 / >=95% boarded
    boarding --> delayed: weather, incident, or manual hold
    delayed --> boarding: hold lifted
    delayed --> cancelled: delay >=180 min or manual cancel
    departed --> airborne: T+5 min
    airborne --> approach: ETA-20 min
    approach --> landed: ETA / runway and weather permit
    approach --> delayed: runway unavailable
    landed --> taxiing: ATA+2 min
    taxiing --> at_gate: ATA+8 min / gate available
    at_gate --> [*]
    cancelled --> [*]
```

## 5. Weather cascade into operations

Weather changes reduce runway capacity first. The resulting holding and
sequencing delays can then propagate through flights, gates, passengers,
baggage, and the financial layer.

```mermaid
flowchart TD
    weather[Weather FSM\nCAVOK -> VMC -> IMC -> LIFR]
    capacity[Reduced runway capacity\n18/16 movements per hour in IMC\n8/6 in LIFR]
    holding[Arrivals enter holding stack]
    flight[Flight service\narrival holds and departure delays]
    gate[Gate conflict\npossible reassignment]
    pax[Passenger service\nconnection and gate alerts]
    bag[Baggage service\nhold or offload bags]
    downstream[Turnaround flight\nrepeat cascade, max depth 5]
    incident[Incident service\nsevere_weather incident and alert]
    cost[Cost service\ncompensation, fuel, handling costs]
    dashboard[Gateway -> dashboard\nreal-time operational picture]

    weather --> capacity
    weather --> incident
    capacity --> holding --> flight
    incident --> flight
    flight --> gate
    flight --> pax
    flight --> bag
    flight --> downstream
    pax --> cost
    bag --> cost
    flight --> cost
    incident --> dashboard
    flight --> dashboard
```

## 6. Incident cascade example

The incident service turns a local hazard into bounded, observable child
effects. This example follows the documented runway-incursion protocol.

```mermaid
flowchart LR
    inject[Manual POST /sim/inject\nor probabilistic trigger]
    created[IncidentCreated\nrunway_incursion]
    stop[RUNWAY_STOP\nrunway status = incident]
    delayed[Flights on runway\ndelayed or go-around]
    holding[runway_closure_holding_stack\ndepth 1]
    ground[departure_ground_stop\ndepth 2]
    congestion[gate_congestion\ndepth 3]
    alerts[IncidentAlert + dashboard updates]
    resolved[Runway cleared\nIncidentStatusChanged: resolved]

    inject --> created --> stop
    stop --> delayed
    delayed --> holding --> ground --> congestion
    created --> alerts
    congestion --> alerts
    stop --> resolved
```

## 7. Neo4j operational graph

Neo4j stores the airport’s structural relationships. These traversals let the
system connect operational state across flights, people, baggage, and
infrastructure.

```mermaid
flowchart TD
    airport((Airport\nART / KART))
    terminal[Terminal\nA, B, or C]
    gate[Gate\nA01 ... C14]
    runway[Runway\n09L / 27R / 09R / 27L]
    flight[Flight\nstatus, times, delay]
    passenger[Passenger\nstatus, location, connection]
    baggage[Baggage\nstatus, tag, scan zone]
    weather[WeatherState\ncategory and runway impact]
    incident[Incident\nseverity, status, affected IDs]
    cost[CostRecord\noperational and disruption cost]

    airport -->|HAS_TERMINAL| terminal
    terminal -->|HAS_GATE| gate
    airport -->|HAS_RUNWAY| runway
    flight -->|ASSIGNED_TO| gate
    flight -->|USES| runway
    passenger -->|BOOKED_ON| flight
    baggage -->|BELONGS_TO| passenger
    baggage -->|LOADED_ON| flight
    weather -->|IMPACTS| runway
    incident -->|AFFECTS| runway
    incident -->|AFFECTS| gate
    incident -->|AFFECTS| flight
    cost -->|INCURRED_BY| flight
    cost -->|RELATED_TO| incident
```

## Sources

- [`docs/architecture/OVERVIEW.md`](../docs/architecture/OVERVIEW.md)
- [`docs/architecture/EVENT_BUS.md`](../docs/architecture/EVENT_BUS.md)
- [`docs/architecture/DATA_MODEL.md`](../docs/architecture/DATA_MODEL.md)
- [`docs/architecture/SIMULATION.md`](../docs/architecture/SIMULATION.md)
- [`docs/services/flight-service/SPEC.md`](../docs/services/flight-service/SPEC.md)
- [`docs/services/incident-service/SPEC.md`](../docs/services/incident-service/SPEC.md)
- [`docs/services/api-gateway/SPEC.md`](../docs/services/api-gateway/SPEC.md)
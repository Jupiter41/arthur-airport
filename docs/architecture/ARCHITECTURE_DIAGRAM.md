# Architecture diagram

> **Format:** [Mermaid](https://mermaid.js.org/) — renders natively on GitHub and in VS Code with the Mermaid preview extension.

---

## System overview

```mermaid
graph TB
    subgraph Frontend["React Dashboard :5173"]
        FB[Flight Board]
        PF[Passenger Flow]
        BT[Baggage Tracker]
        GO[Ground Ops]
        IC[Incident Console]
    end

    subgraph Gateway["API Gateway · Node.js :3000"]
        AUTH[JWT Auth]
        PROXY[REST Proxy]
        WSFAN[WS Fan-out]
        AGG["/airport Aggregate"]
        RL[Rate Limiter]
    end

    Frontend -->|REST + WebSocket| Gateway

    subgraph Services["Domain Services · Python / FastAPI"]
        FS["flight-service :8001<br/>9-state FSM · runway queue<br/>gate resolver · turnaround"]
        PS["passenger-service :8002<br/>security queues · connection risk<br/>LightGBM forecast · zone density"]
        BS["baggage-service :8003<br/>conveyor pipeline · DG screening<br/>offload · zone throughput"]
        WS["weather-service :8004<br/>4-state FSM · METAR/TAF<br/>runway capacity"]
        IS["incident-service :8005<br/>cascade engine · protocols<br/>TTR · reports"]
        SO["sim-orchestrator :8006<br/>virtual clock · schedule seed<br/>probabilistic injection"]
    end

    Gateway -->|HTTP proxy| FS
    Gateway -->|HTTP proxy| PS
    Gateway -->|HTTP proxy| BS
    Gateway -->|HTTP proxy| WS
    Gateway -->|HTTP proxy| IS
    Gateway -->|HTTP proxy| SO

    subgraph Kafka["Apache Kafka :9092"]
        SC[sim.clock]
        FE[flights.events]
        FSched[flights.schedule]
        PE[passengers.events]
        BE[baggage.events]
        WE[weather.events]
        IE[incidents.events]
        IA[incidents.alerts]
        II[incidents.inject]
    end

    SO -->|SimClockTick| SC
    SO -->|FlightScheduleSeeded| FSched
    SO -->|InjectIncident| II

    FS -->|FlightStatusChanged<br/>FlightGateAssigned<br/>FlightCancelled| FE
    PS -->|PassengerStatusChanged<br/>PassengerAlert| PE
    BS -->|BaggageStatusChanged<br/>BaggageFlagged| BE
    WS -->|WeatherStateChanged<br/>METARIssued| WE
    IS -->|IncidentCreated<br/>IncidentStatusChanged| IE
    IS -->|IncidentAlert| IA

    SC -->|consumes| FS
    SC -->|consumes| PS
    SC -->|consumes| BS
    SC -->|consumes| WS
    SC -->|consumes| IS

    WE -->|consumes| FS
    IE -->|consumes| FS
    FSched -->|consumes| FS

    FE -->|consumes| PS
    IE -->|consumes| PS

    FE -->|consumes| BS
    IE -->|consumes| BS

    II -->|consumes| IS
    WE -->|consumes| IS
    BE -->|consumes| IS
    PE -->|consumes| IS

    SC -.->|Kafka consumer| Gateway
    FE -.->|Kafka consumer| Gateway
    PE -.->|Kafka consumer| Gateway
    BE -.->|Kafka consumer| Gateway
    WE -.->|Kafka consumer| Gateway
    IE -.->|Kafka consumer| Gateway
    IA -.->|Kafka consumer| Gateway

    subgraph Storage["Neo4j :7687"]
        N4J[(Graph DB<br/>Flights · Passengers<br/>Baggage · Gates<br/>Runways · Incidents)]
    end

    FS --> N4J
    PS --> N4J
    BS --> N4J
    WS --> N4J
    IS --> N4J
    SO --> N4J

    subgraph Observability["Observability"]
        PROM[Prometheus :9090]
        GRAF[Grafana :3001]
    end

    FS -.->|/metrics| PROM
    PS -.->|/metrics| PROM
    BS -.->|/metrics| PROM
    WS -.->|/metrics| PROM
    IS -.->|/metrics| PROM
    SO -.->|/metrics| PROM
    PROM --> GRAF
```

---

## Kafka event flow

```mermaid
flowchart LR
    SO((sim-orchestrator)) -->|SimClockTick<br/>every sim-minute| CLOCK[sim.clock]

    CLOCK --> FS((flight))
    CLOCK --> PS((passenger))
    CLOCK --> BS((baggage))
    CLOCK --> WS((weather))
    CLOCK --> IS((incident))

    WS -->|WeatherStateChanged| WE[weather.events]
    WE --> FS
    WE --> IS

    FS -->|FlightStatusChanged<br/>FlightGateAssigned<br/>FlightCancelled| FE[flights.events]
    FE --> PS
    FE --> BS

    IS -->|IncidentCreated<br/>IncidentStatusChanged| IE[incidents.events]
    IE --> FS
    IE --> PS
    IE --> BS

    PS -->|PassengerStatusChanged<br/>SecurityCongestionDetected| PE[passengers.events]
    PE --> IS

    BS -->|BaggageStatusChanged<br/>BaggageFlagged| BE[baggage.events]
    BE --> IS

    SO -->|InjectIncident| II[incidents.inject]
    II --> IS

    IS -->|IncidentAlert| IA[incidents.alerts]
```

---

## Cascade delay propagation

```mermaid
flowchart TB
    DELAY[Flight delayed / cancelled] --> GATE[Gate conflict?]
    GATE -->|yes| REASSIGN[FlightGateAssigned<br/>reassign to fallback gate]
    REASSIGN --> PAX_ALERT1[PassengerAlert<br/>gate change]

    DELAY --> CONN[Connecting passengers?]
    CONN -->|delay > 45 min| AT_RISK[PassengerAlert<br/>connection at risk]
    AT_RISK -->|delay > MCT| MISSED[PassengerStatus → missed_connection]

    DELAY --> BAG[Baggage impact?]
    BAG -->|flight cancelled + loaded| OFFLOAD[BaggageStatus → offloaded → carousel]
    BAG -->|significant delay| HOLD[BaggageStatus → hold in make-up]

    DELAY --> TURN[Turnaround aircraft?]
    TURN -->|delay ≥ 15 min| PROP[Outbound departure delayed<br/>by max 0 delay − buffer]
    PROP -->|repeat| DELAY
    PROP -.->|max depth: 5| STOP((stop))
```

---

## Incident cascade tree

```mermaid
flowchart TB
    RI[runway_incursion] --> RCH[runway_closure_holding_stack]
    RCH --> DGS[departure_ground_stop]
    DGS --> GC[gate_congestion]

    BF[baggage_fire] --> MZO[make_up_zone_offline]
    MZO --> FBN[flight_baggage_not_loaded]

    SB[security_breach] --> ZL[zone_lockdown]
    ZL --> SQF[security_queue_frozen]
    SQF --> BD[boarding_delayed]
    BD --> FD[flight_delayed]

    SW[severe_weather] --> RCR[runway_capacity_reduction]
    RCR --> HS[holding_stack]
    HS --> DGD[departure_ground_delay]
    DGD --> FDC[flight_delays_cascade]

    SF[system_failure] --> BTR[baggage_throughput_reduction]
    BTR --> MD[make_up_delay]
    MD --> FBN2[flight_baggage_not_loaded]

    SC[security_congestion] --> BD2[boarding_delayed]
```

---

## Weather FSM

```mermaid
stateDiagram-v2
    [*] --> CAVOK
    CAVOK --> CAVOK: 0.85
    CAVOK --> VMC: 0.13
    CAVOK --> IMC: 0.02

    VMC --> CAVOK: 0.20
    VMC --> VMC: 0.65
    VMC --> IMC: 0.14
    VMC --> LIFR: 0.01

    IMC --> CAVOK: 0.05
    IMC --> VMC: 0.30
    IMC --> IMC: 0.55
    IMC --> LIFR: 0.10

    LIFR --> VMC: 0.05
    LIFR --> IMC: 0.35
    LIFR --> LIFR: 0.60

    note right of CAVOK
        Vis > 10km
        32 arr + 32 dep/hr
        Both runways
    end note

    note right of LIFR
        Vis < 1.5km
        8 arr + 6 dep/hr
        CAT III ILS only
    end note
```

---

## Flight state machine

```mermaid
stateDiagram-v2
    [*] --> scheduled

    scheduled --> boarding: T−60 min (departure)
    scheduled --> approach: T−20 min (arrival)
    scheduled --> delayed: gate unavailable
    scheduled --> cancelled: operator

    boarding --> departed: T−0 + ≥95% boarded
    boarding --> delayed: hold / weather / incident
    boarding --> cancelled: delay ≥ 180 min

    delayed --> boarding: hold lifted (departure)
    delayed --> approach: hold lifted (arrival)
    delayed --> cancelled: delay ≥ 180 min

    departed --> airborne: T+5 min

    airborne --> approach: T−20 min (arrival)

    approach --> landed: at ETA + runway available
    approach --> delayed: runway unavailable

    landed --> taxiing: +5 min

    taxiing --> at_gate: gate available

    at_gate --> [*]
    cancelled --> [*]
```

---

## Passenger flow (departure)

```mermaid
stateDiagram-v2
    [*] --> checked_in
    checked_in --> security_queue: T−45 min before departure
    security_queue --> airside: cleared security
    airside --> at_gate: gate opens (T−30) + dwell elapsed
    at_gate --> boarded: boarding call (T−20)
    boarded --> [*]
```

---

## Baggage pipeline

```mermaid
flowchart LR
    DROPP[Drop-off] --> IND[Induction<br/>600/hr per terminal]
    IND --> SCR[Screening<br/>300/hr per unit<br/>6 units total]
    SCR -->|clear| SORT[Sorting Matrix<br/>1800/hr]
    SCR -->|DG detected| FLAG[Flagged<br/>manual inspection]
    SORT --> MU[Make-up<br/>150/hr per carousel<br/>15 carousels]
    MU --> LOADED[Loaded on aircraft]
    LOADED --> ARRIVE[Arrived]
    ARRIVE --> CAR[Arrival Belt<br/>200/hr per belt<br/>6 belts]
    CAR --> COL[Collected]
```

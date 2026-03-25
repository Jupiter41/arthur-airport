# incident-service

> 📄 **Specification:** [docs/services/incident-service/SPEC.md](../../docs/services/incident-service/SPEC.md)
> 🧠 **Skill file:** [SKILL.md](./SKILL.md)

**Language:** Python 3.11 · **Framework:** FastAPI · **Port:** 8005

Owns the full lifecycle of hazardous events at KART. Manages cascade propagation, emergency protocol activation, alert generation, and automated incident report creation. Supports both manual injection and probabilistic simulation.

---

## Architecture

```
incident-service/
├── main.py              # FastAPI app, lifespan, WebSocket endpoint
├── metrics.py           # Prometheus metric definitions
├── models/
│   └── domain.py        # Pydantic models: Incident, CascadeTree, Alert, Report
├── routers/
│   └── incidents.py     # REST endpoints: list, detail, inject, contain, resolve
├── kafka/
│   ├── consumer.py      # IncidentConsumerState, tick lifecycle, cross-domain handlers
│   └── producer.py      # Emits IncidentCreated, IncidentStatusChanged, alerts
├── services/
│   ├── lifecycle.py     # create/contain/resolve logic, TTR countdown
│   ├── cascade.py       # Rule-based child incident spawning (depth-limited)
│   ├── protocols.py     # ProtocolManager: RUNWAY_STOP, FULL_EVACUATION, etc.
│   └── reports.py       # Auto-generated incident report/timeline builder
└── db/
    └── neo4j.py         # Incident CRUD, AFFECTS/SPAWNED relationships, cascade tree
```

## Incident types and cascade trees

| Root incident           | Cascade chain                                                               | Max depth |
| ----------------------- | --------------------------------------------------------------------------- | --------- |
| **runway_incursion**    | → runway_closure → ground_stop → gate_congestion                            | 3         |
| **baggage_fire**        | → make_up_zone_offline → flight_baggage_not_loaded                          | 2         |
| **security_breach**     | → zone_lockdown → queue_frozen → boarding_delayed → flight_delayed          | 4         |
| **severe_weather**      | → capacity_reduction → holding_stack → ground_delay → flight_delays_cascade | 4         |
| **system_failure**      | → throughput_reduction → make_up_delay → baggage_not_loaded                 | 3         |
| **security_congestion** | → boarding_delayed                                                          | 1         |

### TTR (time-to-resolve) ranges

| Type             | TTR range (sim-minutes)       |
| ---------------- | ----------------------------- |
| runway_incursion | 15–45                         |
| baggage_fire     | 20–60                         |
| security_breach  | 30–90                         |
| system_failure   | 10–120                        |
| severe_weather   | weather-driven (no fixed TTR) |

### Emergency protocols

| Protocol             | Trigger                    | Actions                             |
| -------------------- | -------------------------- | ----------------------------------- |
| `RUNWAY_STOP`        | runway_incursion (high+)   | All ground traffic stop; go-around  |
| `BAGGAGE_HOLD`       | baggage_fire (medium+)     | ARFF dispatch; make-up evacuated    |
| `ZONE_LOCKDOWN`      | security_breach (medium)   | Pier sealed; re-screening           |
| `TERMINAL_LOCKDOWN`  | security_breach (high)     | Terminal closed; boarding suspended |
| `FULL_EVACUATION`    | security_breach (critical) | All terminals evacuated             |
| `LOW_VIS_PROCEDURES` | severe_weather (medium+)   | CAT II/III ILS; reduced taxi speed  |

Protocols have override semantics: `FULL_EVACUATION` overrides all others.

## Running

```bash
docker compose up --build

# Just this service
docker compose up neo4j zookeeper kafka
cd services/incident-service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8005 --reload
```

API docs at **http://localhost:8005/docs**

## Key endpoints

| Method | Path                             | Description                                          |
| ------ | -------------------------------- | ---------------------------------------------------- |
| GET    | `/api/v1/incidents`              | All incidents (filterable by status, type, severity) |
| GET    | `/api/v1/incidents/{id}`         | Full detail + cascade tree                           |
| POST   | `/api/v1/incidents/inject`       | Manually inject an event                             |
| POST   | `/api/v1/incidents/{id}/contain` | Mark as contained                                    |
| POST   | `/api/v1/incidents/{id}/resolve` | Mark as resolved                                     |
| GET    | `/api/v1/incidents/{id}/report`  | Auto-generated incident report                       |
| GET    | `/api/v1/alerts`                 | Active alert feed                                    |
| GET    | `/api/v1/protocols`              | Active emergency protocols                           |
| WS     | `/ws/incidents`                  | Real-time incident + alert stream                    |

## Kafka topics

| Direction | Topic               | Events                                                                   |
| --------- | ------------------- | ------------------------------------------------------------------------ |
| Consumes  | `sim.clock`         | `SimClockTick` — advances TTR countdown, fires pending cascades          |
| Consumes  | `incidents.inject`  | `InjectIncident` — manual or probabilistic injection                     |
| Consumes  | `weather.events`    | `WeatherStateChanged` — auto-creates severe_weather incident on IMC/LIFR |
| Consumes  | `baggage.events`    | `BaggageFlagged` — can trigger baggage_fire incident                     |
| Consumes  | `passengers.events` | `SecurityCongestionDetected` — creates security_congestion incident      |
| Produces  | `incidents.events`  | `IncidentCreated`, `IncidentStatusChanged`, `IncidentCascade`            |
| Produces  | `incidents.alerts`  | `IncidentAlert` for dashboard notifications                              |

## Testing

```bash
python -m pytest tests/unit/ -k incident -v
```

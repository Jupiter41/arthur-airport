# SKILL — incident-service

## Incident lifecycle · Cascade engine · Emergency protocols · TTR · Reports

> Full specification: `docs/services/incident-service/SPEC.md`
> Read `docs/skills/SKILL.md` and `docs/skills/python-service.SKILL.md` first.

---

## Incident creation flow

Every incident — whether manual or probabilistic — goes through this single function:

```python
from uuid import uuid4

async def create_incident(
    type: str,
    severity: str,
    location: str,
    trigger: str,          # "manual" | "probabilistic" | "cascade" | "auto"
    sim_time: datetime,
    description: str = "",
    cascade_depth: int = 0,
    parent_id: str | None = None,
) -> dict:
    incident_id = str(uuid4())
    ttr = sample_ttr(type)

    incident = {
        "id": incident_id,
        "type": type,
        "severity": severity,
        "status": "active",
        "trigger": trigger,
        "location": location,
        "description": description or DEFAULT_DESCRIPTIONS[type],
        "protocol": PROTOCOLS[type][severity],
        "started_at": sim_time.isoformat(),
        "ttr_minutes": ttr,
        "ttr_remaining": ttr,
        "cascade_depth": cascade_depth,
    }

    await write_incident_to_neo4j(incident)
    if parent_id:
        await create_spawned_relationship(parent_id, incident_id, sim_time)

    await produce_incident_created(incident, sim_time)
    await produce_incident_alert(incident, sim_time)
    await activate_protocol(incident, sim_time)
    await evaluate_cascades(incident, sim_time)

    return incident
```

---

## TTR sampling

```python
import random

TTR_RANGES = {
    "runway_incursion":    (15, 45),
    "baggage_fire":        (20, 60),
    "security_breach":     (30, 90),
    "system_failure":      (10, 120),
    "security_congestion": None,   # auto-resolves via passenger-service signal
    "severe_weather":      None,   # auto-resolves when weather improves
}

def sample_ttr(incident_type: str) -> int | None:
    r = TTR_RANGES.get(incident_type)
    return random.randint(*r) if r else None
```

---

## TTR countdown (every SimClockTick)

```python
async def tick_ttr(sim_time: datetime):
    active = await get_active_incidents_with_ttr()
    for incident in active:
        if incident["ttr_remaining"] is None:
            continue
        incident["ttr_remaining"] -= 1
        await update_ttr_remaining(incident["id"], incident["ttr_remaining"])
        if incident["ttr_remaining"] <= 0:
            await auto_resolve(incident["id"], sim_time)
```

---

## Cascade rule table

```python
CASCADE_RULES: dict[str, list[dict]] = {
    "runway_incursion": [
        {
            "child_type": "runway_closure_holding_stack",
            "min_severity": "high",
            "delay_sim_min": 0,
            "child_severity": "high",
        },
    ],
    "runway_closure_holding_stack": [
        {
            "child_type": "departure_ground_stop",
            "min_severity": "high",
            "delay_sim_min": 1,
            "child_severity": "medium",
        },
    ],
    "departure_ground_stop": [
        {
            "child_type": "gate_congestion",
            "min_severity": "medium",
            "delay_sim_min": 2,
            "child_severity": "low",
        },
    ],
    "security_breach": [
        {
            "child_type": "zone_lockdown",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "zone_lockdown": [
        {
            "child_type": "security_queue_frozen",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "medium",
        },
    ],
    "security_queue_frozen": [
        {
            "child_type": "boarding_delayed",
            "min_severity": "medium",
            "delay_sim_min": 5,
            "child_severity": "low",
        },
    ],
    "system_failure": [
        {
            "child_type": "baggage_throughput_reduction",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
            "subtype_filter": ["conveyor_jam", "conveyor-sorting",
                               "conveyor-induction-A", "conveyor-induction-B",
                               "conveyor-induction-C"],
        },
    ],
    "security_congestion": [
        {
            "child_type": "boarding_delayed",
            "min_severity": "medium",
            "delay_sim_min": 0,
            "child_severity": "low",
        },
    ],
}

SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}

async def evaluate_cascades(parent: dict, sim_time: datetime):
    depth = parent.get("cascade_depth", 0)
    if depth >= load_airport_runtime_config().operations.cascade_max_depth:
        return

    rules = CASCADE_RULES.get(parent["type"], [])
    for rule in rules:
        if SEVERITY_RANK[parent["severity"]] < SEVERITY_RANK[rule["min_severity"]]:
            continue
        await create_incident(
            type=rule["child_type"],
            severity=rule["child_severity"],
            location=parent["location"],
            trigger="cascade",
            sim_time=sim_time,
            cascade_depth=depth + 1,
            parent_id=parent["id"],
        )
```

---

## Emergency protocols

```python
PROTOCOLS: dict[str, dict[str, str]] = {
    "runway_incursion":    {"high": "RUNWAY_STOP", "critical": "RUNWAY_STOP"},
    "baggage_fire":        {"medium": "BAGGAGE_HOLD", "high": "BAGGAGE_HOLD"},
    "security_breach":     {
        "medium": "ZONE_LOCKDOWN",
        "high": "TERMINAL_LOCKDOWN",
        "critical": "FULL_EVACUATION",
    },
    "severe_weather":      {"medium": "LOW_VIS_PROCEDURES", "critical": "LOW_VIS_PROCEDURES"},
    "system_failure":      {"low": "", "medium": "", "high": ""},
    "security_congestion": {"medium": "", "high": ""},
}

DEFAULT_DESCRIPTIONS = {
    "runway_incursion": "Vehicle or aircraft detected on active runway without clearance.",
    "baggage_fire": "Fire or dangerous goods hazard detected in baggage handling area.",
    "security_breach": "Unauthorized individual or object detected in restricted zone.",
    "severe_weather": "Weather conditions degraded to instrument flight rules.",
    "system_failure": "Infrastructure failure detected in airport systems.",
    "security_congestion": "Security queue wait time exceeds operational threshold.",
}
```

---

## Auto-generated incident report

```python
async def build_report(incident_id: str, sim_time: datetime) -> dict:
    incident = await get_incident(incident_id)
    cascades = await get_cascade_tree(incident_id)
    affected_flights = await get_affected_flights(incident_id)
    total_delay = sum(f.get("delay_minutes", 0) for f in affected_flights)

    duration_min = None
    if incident.get("resolved_at"):
        resolved = datetime.fromisoformat(incident["resolved_at"])
        started  = datetime.fromisoformat(incident["started_at"])
        duration_min = int((resolved - started).total_seconds() / 60)

    return {
        "incident_id": incident_id,
        "report_generated_at": sim_time.isoformat(),
        "title": f"{incident['type'].replace('_', ' ').title()} — "
                 f"{incident['location']} — {incident['started_at'][:10]}",
        "type": incident["type"],
        "severity": incident["severity"],
        "trigger": incident["trigger"],
        "timeline_summary": build_timeline_summary(incident, cascades, duration_min),
        "total_flights_affected": len(affected_flights),
        "total_delay_minutes_caused": total_delay,
        "cascade_events": len(cascades),
        "protocols_activated": [incident.get("protocol")] if incident.get("protocol") else [],
        "recommendations": RECOMMENDATIONS.get(incident["type"], []),
    }
```

---

## Kafka produced events

| Event                   | Trigger                                      |
| ----------------------- | -------------------------------------------- |
| `IncidentCreated`       | New incident (any trigger)                   |
| `IncidentStatusChanged` | Status change: active → contained → resolved |
| `IncidentCascaded`      | Child incident spawned                       |
| `IncidentAlert`         | Every new incident + every status change     |

## Kafka topics consumed

| Topic               | Event                         | Action                                   |
| ------------------- | ----------------------------- | ---------------------------------------- |
| `sim.clock`         | `SimClockTick`                | Tick TTR countdown, auto-resolve expired |
| `incidents.inject`  | `InjectIncident`              | Create manual incident                   |
| `weather.events`    | `WeatherStateChanged`         | Auto-create severe_weather on IMC/LIFR   |
| `baggage.events`    | `BaggageFlagged` (dg_class=3) | Probabilistic baggage_fire trigger       |
| `passengers.events` | `SecurityCongestionDetected`  | Create security_congestion incident      |

---

## Mid-simulation startup & restart convergence

When this service starts (or restarts) while the simulation is already running:

1. **Rebuild active incidents** — `IncidentConsumerState.rebuild_from_neo4j()` loads all `Incident` nodes with status `active` or `mitigating` and populates the in-memory lifecycle manager.
2. **Pending cascades** — the cascade scheduler rebuilds from Neo4j `CASCADED_FROM` relationships and re-enqueues pending child incidents with their remaining delay.
3. **Protocol state** — active protocols are loaded from `Protocol` nodes in Neo4j.
4. **TTR timers** — resolution timers are recalculated from `created_at` timestamps; incidents that should have resolved are resolved on the first tick.
5. **Alert cache** — rebuilt from Neo4j incident data; stale alerts are not replayed.
6. **Impact links** — `AFFECTS` relationships between incidents and flights/gates/runways are already in Neo4j and are re-queried as needed.

**Tests:** `tests/integration/test_resilience.py::TestServiceRestart` (covered indirectly via full restart)

---

## Gotchas

- **Always produce `IncidentAlert` on every status change** — not just on creation. Dashboards rely on alerts to update their notification panels.
- **`severe_weather` and `security_congestion` have no TTR** — they must be auto-resolved by an external signal, not by countdown. Severe weather resolves when `WeatherStateChanged` returns to VMC or CAVOK. Security congestion resolves when wait drops below 15 min for 3 consecutive ticks.
- **Cascade depth is tracked per-chain, not globally.** A runway incursion at depth 0 and a simultaneous security breach at depth 0 are separate chains — they do not share the depth counter.
- **Do not produce a cascade child if depth >= CASCADE_MAX_DEPTH.** Still produce `IncidentAlert` but do not call `create_incident()` — this is the hard stop.
- **`FULL_EVACUATION` protocol overrides all others.** If a critical security breach fires while another protocol is active, FULL_EVACUATION takes precedence.

### Testing notes

- **`lifecycle.py` imports `db.neo4j` at module level.** To unit test TTR ranges, protocol mappings, and transition validation, you must pre-install mock `db` and `db.neo4j` modules in `sys.modules` before importing. See `tests/unit/test_incident_lifecycle.py`.
- **Cascade rules are a dictionary** — test by verifying no chain exceeds `CASCADE_MAX_DEPTH` (5), no circular references exist, and all primary incident types have entries.
- **`sample_ttr()` returns `None` for `severe_weather` and `security_congestion`** — these types resolve externally, not by countdown.

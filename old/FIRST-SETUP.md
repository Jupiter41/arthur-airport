# First Run — Guided Scenario

You've built all 9 base sprints. The stack is up. Now what?

This guide walks you through a **20-minute live demo** that exercises every service, every
dashboard, and the full incident cascade pipeline.

---

## 1. Start the stack

```bash
docker compose up --build
```

Wait until all health checks pass (~90 seconds). You can watch the logs for
`sim-orchestrator` to confirm seeding is done — look for `"Clock started"`.

---

## 2. Open these pages side by side

Arrange your browser with **4 tabs** (or use split-screen):

| Tab              | URL                              | What to watch                               |
| ---------------- | -------------------------------- | ------------------------------------------- |
| Flight Board     | http://localhost:5173/           | Departures/arrivals updating in real time   |
| Passenger Flow   | http://localhost:5173/passengers | Security queue heatmap, at-risk connections |
| Incident Console | http://localhost:5173/incidents  | Will be empty — for now                     |
| Ground Ops       | http://localhost:5173/ground-ops | Runway strips, gate occupancy               |

Optional extras:

| Page            | URL                                              |
| --------------- | ------------------------------------------------ |
| Baggage Tracker | http://localhost:5173/baggage                    |
| Neo4j Browser   | http://localhost:7474 (neo4j / art-digital-twin) |
| Kafka UI        | http://localhost:8080                            |
| Grafana         | http://localhost:3001 (admin / art-grafana)      |

---

## 3. Get an auth token

Every API call through the gateway needs a JWT. Grab one:

```bash
TOKEN=$(curl -s -X POST http://localhost:3000/auth/token \
  -H 'Content-Type: application/json' \
  -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)
```

Verify it works:

```bash
curl -s http://localhost:3000/api/v1/sim/status \
  -H "Authorization: Bearer $TOKEN" | jq
```

You should see `running: true`, the current `sim_time`, and `speed_multiplier: 60`.

---

## 4. Let the simulation breathe

The sim starts at **Day 1, 06:00** at **60× speed** (1 real second = 1 simulated minute).

Watch the Flight Board for a couple of minutes. You'll see:

- Flights cycling through `scheduled → boarding → departed → airborne → landed`
- Gate assignments filling and releasing
- Weather METAR refreshing (check the weather strip on the Flight Board)
- Passenger counts shifting through security → airside → gates
- Baggage flowing through check-in → screening → make-up → loading

This is normal operations. Everything is calm. Take it in.

---

## 5. Speed up to reach peak traffic

Push the sim to **600×** so the airport gets into its busy mid-morning window:

```bash
curl -s -X PATCH http://localhost:3000/api/v1/sim/speed \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"multiplier": 600}' | jq
```

Watch the dashboard update rapidly. After ~10 seconds of real time (≈100 sim minutes), you'll be
mid-morning with lots of flights in play. Now bring it back to a watchable pace:

```bash
curl -s -X PATCH http://localhost:3000/api/v1/sim/speed \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"multiplier": 60}' | jq
```

---

## 6. Trigger an incident — runway incursion

This is the fun part. Switch to your **Incident Console** tab and inject a critical incident:

```bash
curl -s -X POST http://localhost:3000/api/v1/incidents/inject \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "runway_incursion",
    "severity": "critical",
    "location": "runway-09L",
    "description": "Vehicle entered active runway during landing sequence"
  }' | jq
```

Save the returned `incident_id` — you'll need it later.

### What to watch (across all tabs)

| Dashboard            | What changes                                                                                                                                 |
| -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| **Incident Console** | New incident card appears with `ACTIVE` status. Cascade tree starts growing as downstream effects propagate. Alert feed lights up.           |
| **Ground Ops**       | Runway 09L strip turns red. `RUNWAY_STOP` protocol banner appears. Arriving flights enter holding patterns. Departures on that runway pause. |
| **Flight Board**     | Flights targeting runway 09L flip to `holding` or `delayed`. Cascading delay times ripple to connecting flights. Status badges flash.        |
| **Passenger Flow**   | At-risk connection count spikes as delays propagate. Passengers for delayed flights queue up at gates longer.                                |
| **Baggage Tracker**  | Baggage for held flights stops advancing. Flagged items may appear if loading was interrupted mid-sequence.                                  |

---

## 7. Try a second incident — security breach

Stack a security breach on top while the runway is still closed:

```bash
curl -s -X POST http://localhost:3000/api/v1/incidents/inject \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "security_breach",
    "severity": "high",
    "location": "terminal-A",
    "description": "Unauthorized individual in sterile area near gate A12"
  }' | jq
```

### Additional effects to watch

- **Passenger Flow:** Security zone lockdown in Terminal A. Queue freeze — passengers stop
  advancing through security. The heatmap should show a congestion spike.
- **Ground Ops:** `ZONE_LOCKDOWN` protocol activates alongside the existing `RUNWAY_STOP`.
- **Flight Board:** Flights at Terminal A gates may show additional boarding delays.

---

## 8. Contain and resolve

Once you've observed the cascading chaos (~2-3 minutes), start resolving:

```bash
# Contain the runway incursion (replace INCIDENT_ID with the actual ID)
curl -s -X POST http://localhost:3000/api/v1/incidents/INCIDENT_ID/contain \
  -H "Authorization: Bearer $TOKEN" | jq

# Wait a minute, then resolve it
curl -s -X POST http://localhost:3000/api/v1/incidents/INCIDENT_ID/resolve \
  -H "Authorization: Bearer $TOKEN" | jq
```

### What to watch during recovery

- **Ground Ops:** Runway 09L reopens. Held flights begin landing sequences. Protocol banner clears.
- **Flight Board:** Delayed flights start catching up. Some may still carry residual delay.
- **Incident Console:** Status transitions to `CONTAINED` then `RESOLVED`. Full cascade tree is
  visible showing everything that was affected. You can pull the report:

```bash
curl -s http://localhost:3000/api/v1/incidents/INCIDENT_ID/report \
  -H "Authorization: Bearer $TOKEN" | jq
```

The report shows the incident timeline, all affected entities, total delay minutes, and protocol
activations.

---

## 9. Explore the API

With the sim running, poke around the REST API to see the data behind the dashboards:

```bash
# Airport-wide snapshot (aggregated from all services)
curl -s http://localhost:3000/api/v1/airport \
  -H "Authorization: Bearer $TOKEN" | jq

# Current weather
curl -s http://localhost:3000/api/v1/weather/current \
  -H "Authorization: Bearer $TOKEN" | jq

# Weather impact assessment
curl -s http://localhost:3000/api/v1/weather/impact \
  -H "Authorization: Bearer $TOKEN" | jq

# All flights
curl -s http://localhost:3000/api/v1/flights \
  -H "Authorization: Bearer $TOKEN" | jq

# Passengers at risk of missing connections
curl -s http://localhost:3000/api/v1/passengers/connections/at-risk \
  -H "Authorization: Bearer $TOKEN" | jq

# Baggage flow map
curl -s http://localhost:3000/api/v1/baggage/flow/map \
  -H "Authorization: Bearer $TOKEN" | jq

# Flagged baggage
curl -s http://localhost:3000/api/v1/baggage/flagged \
  -H "Authorization: Bearer $TOKEN" | jq

# All active incidents
curl -s http://localhost:3000/api/v1/incidents \
  -H "Authorization: Bearer $TOKEN" | jq
```

---

## 10. Check observability

Open **Grafana** at http://localhost:3001 (admin / art-grafana).

Pre-provisioned dashboards show:

- Per-service request rates and latencies
- Kafka consumer lag per topic
- Neo4j query durations
- Simulation tick rate health
- Alert rules that fire under degraded conditions

If you triggered an incident, you should see metric spikes correlating with the cascade —
higher request rates on flight-service and incident-service, increased Kafka throughput,
and possibly a fired alert for runway capacity drop.

---

## Quick reference

### Sim speed cheat sheet

| Speed  | Meaning                   | Good for                     |
| ------ | ------------------------- | ---------------------------- |
| `1`    | Real time (1 sec = 1 sec) | Slow detailed observation    |
| `10`   | 10×                       | Watching individual flights  |
| `60`   | 60× (default)             | Normal demo pace             |
| `600`  | 600×                      | Fast-forward to busy periods |
| `3600` | 3600×                     | Skip to next day             |

### Incident types

| Type               | Example location   | Typical severity    |
| ------------------ | ------------------ | ------------------- |
| `runway_incursion` | `runway-09L`       | `high` / `critical` |
| `baggage_fire`     | `baggage-makeup-1` | `medium` / `high`   |
| `security_breach`  | `terminal-A`       | `high` / `critical` |
| `severe_weather`   | `airfield`         | `medium` / `high`   |
| `system_failure`   | `baggage-bhs`      | `low` / `medium`    |

### Pause/resume (if you need to freeze the action)

```bash
curl -s -X POST http://localhost:3000/api/v1/sim/pause \
  -H "Authorization: Bearer $TOKEN" | jq

curl -s -X POST http://localhost:3000/api/v1/sim/resume \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Full reset (wipe everything, start fresh)

```bash
docker compose down -v && docker compose up --build
```

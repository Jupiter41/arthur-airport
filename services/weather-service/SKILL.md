# SKILL — weather-service

## FSM · METAR generation · Runway capacity calculation

> Full specification: `docs/services/weather-service/SPEC.md`
> Read `docs/skills/SKILL.md` and `docs/skills/python-service.SKILL.md` first.

---

## Weather FSM

Four states in order of severity: `CAVOK` (0) → `VMC` (1) → `IMC` (2) → `LIFR` (3)

```python
import random

TRANSITION_MATRIX = {
    "CAVOK": {"CAVOK": 0.85, "VMC": 0.13, "IMC": 0.02, "LIFR": 0.00},
    "VMC":   {"CAVOK": 0.20, "VMC": 0.65, "IMC": 0.14, "LIFR": 0.01},
    "IMC":   {"CAVOK": 0.05, "VMC": 0.30, "IMC": 0.55, "LIFR": 0.10},
    "LIFR":  {"CAVOK": 0.00, "VMC": 0.05, "IMC": 0.35, "LIFR": 0.60},
}

SEVERITY = ["CAVOK", "VMC", "IMC", "LIFR"]

def evaluate_transition(current: str) -> str:
    row = TRANSITION_MATRIX[current]
    candidate = random.choices(
        list(row.keys()), weights=list(row.values())
    )[0]
    # Reject jumps of more than 1 severity step
    if abs(SEVERITY.index(candidate) - SEVERITY.index(current)) > 1:
        return current  # stay — re-evaluate next hour
    return candidate
```

**Critical:** only evaluate FSM transition when `sim_time.minute == 0`.
Do not evaluate on every tick.

---

## Parameter sampling per state

```python
import random
from dataclasses import dataclass

@dataclass
class WeatherParams:
    category: str
    visibility_m: int
    wind_direction: int
    wind_speed_kt: int
    wind_gust_kt: int
    ceiling_ft: int | None
    temperature_c: float
    dew_point_c: float
    qnh_hpa: int
    phenomena: list[str]

def sample_params(category: str) -> WeatherParams:
    match category:
        case "CAVOK":
            return WeatherParams(
                category="CAVOK",
                visibility_m=random.randint(10000, 20000),
                wind_direction=random.randint(0, 359),
                wind_speed_kt=random.randint(0, 15),
                wind_gust_kt=0,
                ceiling_ft=None,
                temperature_c=round(random.uniform(10, 25), 1),
                dew_point_c=round(random.uniform(5, 15), 1),
                qnh_hpa=random.randint(1005, 1025),
                phenomena=[],
            )
        case "VMC":
            return WeatherParams(
                category="VMC",
                visibility_m=random.randint(5000, 10000),
                wind_direction=random.randint(0, 359),
                wind_speed_kt=random.randint(5, 25),
                wind_gust_kt=random.choice([0, 0, 0, random.randint(15, 30)]),
                ceiling_ft=random.randint(2000, 5000),
                temperature_c=round(random.uniform(8, 20), 1),
                dew_point_c=round(random.uniform(4, 12), 1),
                qnh_hpa=random.randint(1000, 1022),
                phenomena=random.choices([[], ["FEW"], ["SCT"]], weights=[0.6, 0.3, 0.1])[0],
            )
        case "IMC":
            return WeatherParams(
                category="IMC",
                visibility_m=random.randint(1500, 5000),
                wind_direction=random.randint(0, 359),
                wind_speed_kt=random.randint(15, 35),
                wind_gust_kt=random.randint(20, 45),
                ceiling_ft=random.randint(500, 1500),
                temperature_c=round(random.uniform(2, 12), 1),
                dew_point_c=round(random.uniform(0, 8), 1),
                qnh_hpa=random.randint(990, 1010),
                phenomena=random.choices(
                    [["RA"], ["TS", "RA"], ["FG"], ["SN"]], weights=[0.4, 0.3, 0.2, 0.1]
                )[0],
            )
        case "LIFR":
            return WeatherParams(
                category="LIFR",
                visibility_m=random.randint(100, 1500),
                wind_direction=random.randint(0, 359),
                wind_speed_kt=random.randint(25, 55),
                wind_gust_kt=random.randint(35, 65),
                ceiling_ft=random.randint(50, 500),
                temperature_c=round(random.uniform(-5, 5), 1),
                dew_point_c=round(random.uniform(-7, 3), 1),
                qnh_hpa=random.randint(978, 998),
                phenomena=random.choices(
                    [["TS", "HVY RA"], ["FG"], ["SN", "BLSN"]], weights=[0.5, 0.3, 0.2]
                )[0],
            )
```

---

## METAR string builder

```python
def build_metar(p: WeatherParams, sim_time: datetime) -> str:
    day    = sim_time.day
    hour   = sim_time.hour
    minute = sim_time.minute

    # Wind
    wind = f"{p.wind_direction:03d}{p.wind_speed_kt:02d}"
    if p.wind_gust_kt > 0:
        wind += f"G{p.wind_gust_kt:02d}"
    wind += "KT"

    # Visibility / CAVOK
    if p.category == "CAVOK":
        vis_cloud = "CAVOK"
    else:
        vis_cloud = f"{p.visibility_m:04d}"
        if p.phenomena:
            vis_cloud += " " + " ".join(p.phenomena)
        if p.ceiling_ft:
            oktas = "BKN" if p.ceiling_ft < 1500 else "OVC"
            hundreds = p.ceiling_ft // 100
            vis_cloud += f" {oktas}{hundreds:03d}"

    # Temp / dewpoint
    def fmt_temp(t: float) -> str:
        if t < 0:
            return f"M{abs(int(t)):02d}"
        return f"{int(t):02d}"

    temp = f"{fmt_temp(p.temperature_c)}/{fmt_temp(p.dew_point_c)}"
    qnh  = f"Q{p.qnh_hpa:04d}"

    return f"KART {day:02d}{hour:02d}{minute:02d}Z {wind} {vis_cloud} {temp} {qnh}"
```

---

## Runway capacity calculation

```python
def compute_runway_capacity(p: WeatherParams) -> dict:
    base = {
        "CAVOK": {"arrival": 32, "departure": 32, "runways": 2},
        "VMC":   {"arrival": 28, "departure": 28, "runways": 2},
        "IMC":   {"arrival": 18, "departure": 16, "runways": 1},
        "LIFR":  {"arrival": 8,  "departure": 6,  "runways": 1},
    }[p.category]

    arrival_rate   = base["arrival"]
    departure_rate = base["departure"]

    # Crosswind reduction
    if p.wind_speed_kt > 35:
        arrival_rate   = int(arrival_rate * 0.60)
        departure_rate = int(departure_rate * 0.60)
    elif p.wind_speed_kt > 25:
        arrival_rate   = int(arrival_rate * 0.85)
        departure_rate = int(departure_rate * 0.85)

    # Tailwind reduction (simplified: if wind direction is 090-270 = headwind on 09L)
    tailwind = p.wind_direction > 180
    if tailwind and p.wind_speed_kt > 10:
        arrival_rate   = int(arrival_rate * 0.70)
        departure_rate = int(departure_rate * 0.70)

    return {
        "arrival_rate":   arrival_rate,
        "departure_rate": departure_rate,
        "active_runways": base["runways"],
        "ils_required":   p.category in ("IMC", "LIFR"),
    }
```

---

## Neo4j weather chain update (must be atomic)

```cypher
// Single transaction: create new state, repoint CURRENT_WEATHER, chain to previous
MATCH (a:Airport {icao: 'KART'})
OPTIONAL MATCH (a)-[cw:CURRENT_WEATHER]->(old:WeatherState)
CREATE (w:WeatherState {
  id: $id, category: $category, timestamp: $timestamp,
  visibility_m: $visibility_m, wind_speed_kt: $wind_speed_kt,
  wind_direction: $wind_direction, wind_gust_kt: $wind_gust_kt,
  ceiling_ft: $ceiling_ft, temperature_c: $temperature_c,
  dew_point_c: $dew_point_c, qnh_hpa: $qnh_hpa,
  phenomena: $phenomena, runway_impact: $runway_impact
})
FOREACH (_ IN CASE WHEN old IS NOT NULL THEN [1] ELSE [] END |
  CREATE (w)-[:PREVIOUS_WEATHER]->(old)
  DELETE cw
)
CREATE (a)-[:CURRENT_WEATHER]->(w)
```

---

## Kafka produced events

| Event                 | Trigger                                                   |
| --------------------- | --------------------------------------------------------- |
| `WeatherStateChanged` | FSM transitions to a new state                            |
| `METARIssued`         | Every 30 simulated minutes (regardless of FSM transition) |

## Kafka topics consumed

| Topic       | Event          | Action                                                     |
| ----------- | -------------- | ---------------------------------------------------------- |
| `sim.clock` | `SimClockTick` | Evaluate FSM on hour boundary, emit METAR every 30 sim-min |

---

## Gotchas

- **Evaluate FSM only on hour boundary** — check `sim_time.minute == 0`, not every tick.
- **METAR every 30 sim-minutes** — track last METAR time, emit when `sim_time.minute % 30 == 0`.
- **The Cypher update must be a single transaction** — do not split into multiple `session.run()` calls or you risk a corrupt graph (two CURRENT_WEATHER pointers).
- **`ceiling_ft` is `None` for CAVOK** — handle null in the METAR builder and in the Pydantic model (`Optional[int]`).
- **Phenomena is a list** — store as a Neo4j list property, not a comma-separated string.
- **`severe_weather` incident is created by incident-service**, not weather-service. Weather-service only emits `WeatherStateChanged`. Incident-service consumes it and creates the incident when category is IMC or LIFR.

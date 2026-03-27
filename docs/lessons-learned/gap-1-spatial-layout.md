# Gap 1 — Spatial Layout Implementation Plan

## Objective

Add a physical spatial model to KART airport. Gates, runways, terminals have positions
on a normalized grid. Taxi times and walking times are computed from distances instead
of fixed constants.

---

## Reference data (from ROADMAP.md)

Gate distances from runway 09L threshold:

- Terminal A: A01=800m, A07=1100m, A14=1400m
- Terminal B: B01=1600m, B07=1900m, B14=2200m
- Terminal C: C01=2400m, C07=2700m, C14=3000m

Walking distances:

- Check-in A → Security A: 120m (~1.5 min)
- Security A → Airside A: 80m (~1.0 min)
- Airside A → Gate A01: 50m (~0.7 min)
- Airside A → Gate A14: 300m (~3.5 min)
- Airside A → Gate B01: 400m (~5.0 min, cross-terminal)
- Airside A → Gate C01: 700m (~8.5 min, cross-terminal)

Taxi speeds: taxiway = 15 km/h, apron = 5 km/h
Walking speed: ~1.4 m/s (84 m/min)
Special assistance: walking time × 2.5

---

## Steps

### Step 1: Create `layout.json` fixture

File: `services/sim-orchestrator/fixtures/layout.json`

Encodes:

- Gate positions (x, y) on a normalized 0-1000 grid
- Runway threshold positions
- Terminal centers
- Taxiway/apron boundary distance (for taxi speed split)

### Step 2: Update Neo4j seeding

In `services/sim-orchestrator/db/seed.py`, when creating Gate, Runway, Terminal nodes,
add `position_x` and `position_y` properties from layout.json.

### Step 3: Taxi time utility

File: `services/flight-service/services/spatial.py`

```python
def taxi_time_minutes(runway_pos, gate_pos, apron_boundary=200) -> float:
    distance = euclidean(runway_pos, gate_pos)
    apron_dist = min(distance, apron_boundary)
    taxiway_dist = max(0, distance - apron_boundary)
    # taxiway: 15 km/h = 250 m/min, apron: 5 km/h = 83.3 m/min
    return taxiway_dist / 250 + apron_dist / 83.3
```

### Step 4: Replace fixed taxi constant

In `services/flight-service/services/state_machine.py`:

- `_eval_landed` → use taxi_time_minutes for taxiing transition
- `_eval_taxiing` → use taxi_time_minutes for at_gate transition

### Step 5: Walking time utility

File: `services/passenger-service/services/spatial.py`
or shared in the flight-service spatial module

Computes walking time between zones using terminal layout distances.

### Step 6: Feed walking times into passenger connection risk model

### Step 7: Unit tests

### Step 8: Dashboard visualization (layout map)

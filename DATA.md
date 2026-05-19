# Data Sources — Arthur International Airport

This document describes every data source used by the Arthur International
Airport digital twin, what each one represents, and how it influences the
simulation.

---

## 1. OurAirports Fixture Data

| Field   | Value                                                        |
| ------- | ------------------------------------------------------------ |
| Files   | `data/ourairports/*.csv`                                     |
| Source  | [OurAirports.com](https://ourairports.com/data/) (open data) |
| License | Public domain                                                |

### What it represents

Real-world airport infrastructure data: runways, frequencies, navigation
aids, regions, and countries. This is reference data, not passenger or
flight data.

### How it is used

- **Airport initialization**: runway dimensions, headings, and ILS
  capability are read from `runways.csv` to seed the Neo4j graph when the
  simulation starts. This determines how many runways the airport has,
  their orientations, and whether they support instrument landings.
- **Frequency setup**: `airport-frequencies.csv` provides tower, ground,
  and approach frequencies for realism in the simulation's radio model.
- **Region/country mapping**: used by the fixture loader to classify
  destinations as domestic, short-haul, or long-haul based on geographic
  region codes.

### Why it exists

Provides a realistic airport infrastructure baseline without requiring
manual data entry. Every gate count, runway length, and terminal layout
in the simulation traces back to these fixtures.

---

## 2. BTS T-100 Segment Data (2026)

| Field  | Value                                                                 |
| ------ | --------------------------------------------------------------------- |
| File   | `data/bts/T100_2026.csv`                                              |
| Source | [Bureau of Transportation Statistics](https://www.transtats.bts.gov/) |
| Format | CSV with ~40 columns per record                                       |

### What it represents

Monthly aggregate statistics for every commercial flight segment touching
a US airport: how many departures were scheduled vs. performed, how many
seats were available, and how many passengers actually flew.

### Key columns used

| Column                 | Simulation use                                                                                                       |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `DEPARTURES_PERFORMED` | Route frequency weights — destinations with more real departures are more likely to appear in the simulated schedule |
| `SEATS`                | Capacity constraints — average seat count per departure calibrates aircraft sizing                                   |
| `PASSENGERS`           | Load factor calibration — passengers ÷ seats gives the real load factor per route                                    |
| `MONTH`                | Seasonal variation — monthly load factors create summer peaks and winter troughs                                     |
| `ORIGIN` / `DEST`      | Route identification — maps BTS routes to simulation destinations                                                    |

### How BTS influences simulation behavior

1. **Flight probability models** (`sim-orchestrator/services/schedule.py`):
   When BTS data is loaded, the destination sampling function boosts
   weights for destinations that appear frequently in real-world BTS
   data. A route with 90 monthly departures in BTS gets a higher
   selection probability than one with 15.

2. **Capacity constraints** (`sim-orchestrator/services/bts_calibration.py`):
   Average seats-per-departure from BTS validates the simulation's
   aircraft type selection. If BTS shows a route averages 180 seats but
   the sim picks a 50-seat regional jet, the calibration data flags the
   mismatch.

3. **Delay propagation logic** (indirect):
   Higher load factors from BTS mean more passengers per flight, which
   increases the impact of delays on connecting passenger flows. A flight
   at 95% load factor (BTS-calibrated) generates more missed connections
   than one at 65%.

4. **Per-route load factors** (`sim-orchestrator/services/passengers.py`):
   Instead of using a single global Beta distribution for all flights,
   the passenger generator looks up the BTS load factor for each
   origin–destination pair. Routes that historically fly fuller (e.g.,
   business shuttles) get more passengers; leisure routes with lower
   demand get fewer.

5. **Seasonal curves**:
   Monthly BTS load factors create realistic seasonal patterns — summer
   months show higher passenger counts, winter months show lower ones.

### Passenger-service integration

The `passenger-service` also has a BTS adapter
(`services/passenger-service/services/bts_adapter.py`) that can be
activated at runtime via the dashboard. When active, it replaces the
simulation's passenger flow model with direct BTS historical data,
disaggregated into hourly profiles using a diurnal traffic curve.

---

## 3. OpenFlights Data

| Field   | Value                                                                |
| ------- | -------------------------------------------------------------------- |
| Files   | `data/openflights/airlines.dat`, `data/openflights/routes.dat`, etc. |
| Source  | [OpenFlights.org](https://openflights.org/data.html)                 |
| License | Open Database License                                                |

### What it represents

Global airline and route data: airline names, IATA/ICAO codes, countries,
and active/inactive status.

### How it is used

- **Airline fixtures**: the simulation's airline list (codes, names,
  market shares, fleet composition) is derived from OpenFlights data,
  filtered and enriched for the digital twin's needs.
- **Route plausibility**: route data validates that simulated flight
  connections between airports are operationally realistic.

### Why it exists

Provides realistic airline identities so simulated flights carry
recognizable (but fake) airline codes and names rather than purely random
strings.

---

## 4. ADS-B Live Feed

| Field    | Value                                    |
| -------- | ---------------------------------------- |
| Source   | [adsb.lol](https://www.adsb.lol/) API    |
| Format   | GeoJSON (real-time)                      |
| Endpoint | Queried by `flight-service` ADS-B module |

### What it represents

Real-time positions of actual aircraft broadcasting ADS-B transponder
signals. Includes callsign, altitude, heading, speed, and geographic
coordinates.

### How it is used

- **Track comparison**: the World Map overlays real ADS-B aircraft
  positions alongside simulated flights, allowing visual comparison of
  simulated great-circle routes versus actual flight paths.
- **Deviation measurement**: when a simulated flight is selected, the
  system finds the nearest real ADS-B aircraft on a similar heading and
  reports the deviation in kilometers.
- **ML training feed**: ADS-B position data can feed into the ML
  training pipeline for trajectory prediction models.

### Why it exists

Grounds the simulation in reality — users can see how closely the
simulated traffic patterns match real-world air traffic at any given
moment.

---

## 5. Weather Data (Historical)

| Field  | Value                                                          |
| ------ | -------------------------------------------------------------- |
| Files  | `data/weather/EGLL_30days.csv`, `data/weather/LFPG_30days.csv` |
| Source | Aviation weather archives                                      |
| Format | CSV with METAR-derived fields                                  |

### What it represents

30-day historical weather observations for major hub airports (London
Heathrow, Paris CDG), including visibility, wind speed/direction, ceiling,
and weather categories (VFR/MVFR/IFR/LIFR).

### How it is used

- **Weather injection**: the `weather-service` can replay historical
  weather patterns instead of generating synthetic conditions, giving
  more realistic weather-driven disruption scenarios.
- **Network delay modeling**: weather at remote hub airports influences
  delay propagation — bad weather at EGLL causes inbound delays that
  cascade to KART.

### Why it exists

Weather is the primary driver of airport disruptions. Using real
historical weather patterns produces more realistic delay cascades than
purely random weather generation.

---

## 6. Incident Scenarios

| Field  | Value                                                    |
| ------ | -------------------------------------------------------- |
| Files  | `services/sim-orchestrator/scenarios/definitions/*.yaml` |
| Format | YAML scenario definitions                                |

### What it represents

Pre-defined disruption scenarios: runway closures, medical emergencies,
security threats, network cascade disruptions, and full-capacity stress
tests.

### How incidents affect system behavior

1. **Runway closures** reduce available runway capacity, causing departure
   queues to build up and delays to cascade through the schedule.
2. **Security incidents** trigger terminal evacuations, halting passenger
   flow through security checkpoints and causing mass boarding delays.
3. **Network disruptions** inject delays at remote airports (e.g., EGLL)
   that propagate back to KART via connecting flights — a 45-minute delay
   at Heathrow means late arrivals at KART, missed connections, and
   cascading departure delays.
4. **Full-capacity scenarios** push load factors to 95%+ and flight
   counts to maximum, stress-testing gate assignments, security queues,
   and baggage handling throughput.

### Why it exists

Controlled disruption testing is the core value of a digital twin — the
ability to ask "what happens if runway 09L closes for 90 minutes during
the morning peak?" and get a data-driven answer.

---

## 7. Airport Configuration

| Field  | Value                                        |
| ------ | -------------------------------------------- |
| Files  | `config/airport.yaml`, `config/network.yaml` |
| Format | YAML                                         |

### What it represents

The digital twin's identity and physical layout: airport name (Arthur
International / ART / KART), terminal count, gate assignments, runway
pairs, simulation parameters (daily flight target, load factor mean),
and multi-airport network topology.

### How it is used

- **Airport seeding**: on first startup, the sim-orchestrator reads
  `airport.yaml` to create the Neo4j graph structure — terminals, gates,
  runways, and their relationships.
- **Schedule generation**: `daily_flight_target` and `hourly_weights`
  control how many flights are generated and when they're distributed
  across the day.
- **Network simulation**: `network.yaml` defines remote hub airports,
  their baseline delays, and delay propagation rules for the multi-
  airport network model.

### Why it exists

Makes the entire simulation configurable without code changes. Changing
`daily_flight_target` from 420 to 600 immediately produces a busier
airport with different bottleneck patterns.

---

## Data Flow Summary

```
OurAirports CSV → fixture loader → Neo4j (airport structure)
                                  ↓
BTS T-100 CSV  → bts_calibration → schedule.py (route weights)
                                  → passengers.py (load factors)
                                  ↓
airport.yaml   → airport_config  → schedule.py (flight count, timing)
                                  → passengers.py (global LF params)
                                  ↓
OpenFlights    → fixture loader  → schedule.py (airline selection)
                                  ↓
ADS-B API      → flight-service  → dashboard (live overlay)
                                  ↓
Weather CSV    → weather-service → delay modeling
                                  ↓
Scenarios YAML → scenario engine → incident injection → Kafka events
```

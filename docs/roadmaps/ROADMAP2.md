# Arthur International Airport — Digital Twin Evolution

## Objective

Transform the current model-driven digital twin into a **data-driven, fully prescriptive** decision support system with real business value, capable of answering operational "what-if" questions and reducing costs for airport operators.

---

## 1. Current State

### Architecture

The system is a fully functional event-driven microservices platform:

- **Neo4j** — graph database as single source of truth for all entity relationships (flights, passengers, gates, runways)
- **Apache Kafka** — asynchronous event bus connecting all services, ensuring no silent mutations
- **Simulation clock** — virtual time engine running at configurable speed (1× to 3600×), driving all services via `SimClockTick` events
- **React dashboard** — 11-page frontend with real-time WebSocket push, Mapbox 2D/2.5D and CesiumJS 3D globe
- **API Gateway** — Node.js/Express aggregation layer with WebSocket fan-out
- **8 domain microservices** — Python/FastAPI, each owning a bounded context
- **Airport topology** — physical layout with gates, terminals, runways, taxiways, ground vehicle pools
- **Airport network** — 40+ destination airports with real-world OurAirports data and OpenFlights airlines

### Incidents & Scenarios

- **8 incident types** with configurable probabilities (runway incursion, baggage fire, medical emergency, security breach, etc.)
- **Cascade propagation** — incidents spawn child incidents across services (e.g., runway incursion → holding stack → departure ground stop → gate congestion)
- **Automatic repair** — incidents auto-resolve after time-to-repair (TTR) elapses
- **Scenario builder** — 8 YAML-defined scenarios with CLI runner and REST API
- **AI-powered recommendations** — bottleneck detection, recommendation engine, what-if analysis, autonomous operations mode

### Services

| Service        | What it does                                                                                              |
| -------------- | --------------------------------------------------------------------------------------------------------- |
| **Passengers** | Full passenger flow: check-in → security → gate → boarded, with connections, no-shows, special assistance |
| **Flights**    | Flight lifecycle, gate assignment, runway sequencing, wake turbulence separation, holding patterns        |
| **Baggage**    | Bag tracking from drop-off to carousel, dangerous goods detection, offloading logic                       |
| **Weather**    | Weather state machine (simulated, historical replay, or live METAR), runway impact calculation            |
| **Incidents**  | Hazard lifecycle, cascade triggering, emergency protocols, alert generation                               |
| **Analysis**   | Bottleneck detection, recommendations, what-if simulation, anomaly detection                              |

---

## 2. How to Make It More Business-Oriented

### 2.1 Solidify the Architecture

| Task                                                     | Why                                                                                                                                                                            | Effort      |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------- |
| Full bug review & regression test suite                  | Ensure system reliability before going to production-grade demos                                                                                                               | 1–2 weeks   |
| Evaluate a **context broker** (FIWARE Stellio, Orion-LD) | Standardise data sharing via NGSI-LD, improve interoperability with smart city / SESAR systems. May be overkill for current scope but valuable for EU-funded project alignment | 1 week eval |
| Security hardening                                       | Add proper JWT auth, role-based access, API rate limiting, encrypted secrets — needed before any proprietary deployment or data licensing                                      | 1 week      |
| Data access layer abstraction                            | Allow toggling between simulated and real data sources transparently, without changing service code                                                                            | 2–3 days    |

### 2.2 Real Data — APIs & Datasets

The goal is to **replace simulated data with real-world feeds** to validate the model and enable genuine predictive/prescriptive analytics. Each source should be toggleable (simulated ↔ real) via a configuration switch.

Current implementation status (May 2026):

- Default stack behavior remains simulation-first.
- Some real-data adapters are implemented and optional at runtime (weather live/historical, ADS-B overlay).
- Several business-data integrations in this section are still roadmap items.

#### Flight Data

| Source                           | What it provides                                                                                                    | Pricing                                                                                                                     | Link                                                            | Use for                                                                                                     |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| **FlightAware AeroAPI**          | Real-time & historical flights, delays, routes, positions, disruption stats, weather (METAR/TAF), airline schedules | **Personal**: free (limited). **Standard**: ~$1/query. **Premium**: custom (includes Foresight™ ML predictions)             | [flightaware.com/aeroapi](https://www.flightaware.com/aeroapi/) | Real flight schedules, actual delays/cancellations, route validation, disruption calibration                |
| **Aviationstack**                | Real-time flights, historical data, airline routes, airport info                                                    | **Free**: 100 req/month. **Basic**: $45/month (10k req). **Pro**: $132/month (50k req). **Business**: $425/month (250k req) | [aviationstack.com](https://aviationstack.com/product)          | Bulk flight status, schedule validation, historical delay patterns                                          |
| **adsb.lol**                     | Community ADS-B aggregator, real-time aircraft positions, no auth required, no rate limits                          | **Free** (community-run, donations welcome)                                                                                 | [adsb.lol](https://www.adsb.lol/)                               | **Primary ADS-B source** — real aircraft positions and map overlay (**implemented now**)                    |
| **OpenSky Network**              | ADS-B surveillance data, real-time aircraft positions, historical tracks (Zenodo dumps)                             | **Free** for academic/research. API heavily rate-limited (unauthenticated: 100 req/day, authenticated: 4000 req/day)        | [opensky-network.org](https://opensky-network.org/)             | **Fallback ADS-B source** — used when adsb.lol is unavailable. Historical tracks via Zenodo for calibration |
| **OAG (Official Airline Guide)** | Airline schedules, future & historical, route analytics                                                             | **Enterprise pricing** (typically $5k–$50k/year depending on scope)                                                         | [oag.com](https://www.oag.com/)                                 | Gold standard for airline schedules — expensive but definitive for serious validation                       |

**adsb.lol vs Aviationstack**: These serve different purposes. **adsb.lol** provides real-time ADS-B positions (lat/lon/altitude/heading) — ideal for the map overlay and track comparison. It is community-run, completely free, and has no rate limits. **Aviationstack** provides flight schedule/status data (origin, destination, delays, airline info) — useful for replacing simulated schedules with real ones. They are complementary, not competing: adsb.lol for positions, Aviationstack for schedules.

**Recommendation**: Keep **adsb.lol** as the primary ADS-B position source (already implemented, with OpenSky as fallback), then add **Aviationstack** or **FlightAware** for real schedule/status ingestion to move beyond simulated schedules.

#### Weather Data

| Source                             | What it provides                                          | Pricing                                                      | Link                                                                                  | Use for                                                                                                  |
| ---------------------------------- | --------------------------------------------------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| **Aviation Weather Center (ADDS)** | METAR, TAF, SIGMET, PIREP — official aviation weather     | **Free** (US government, public domain)                      | [aviationweather.gov](https://aviationweather.gov/)                                   | **Integrated as optional live mode** (`WEATHER_SOURCE=live`). Default stack still uses simulated weather |
| **Iowa State Mesonet**             | Historical METAR archives, hourly data going back decades | **Free** (academic)                                          | [mesonet.agron.iastate.edu](https://mesonet.agron.iastate.edu/request/download.phtml) | **Integrated as optional historical replay** (`WEATHER_SOURCE=historical`)                               |
| **Open-Meteo**                     | Forecast + historical weather, no API key required        | **Free** for non-commercial. Commercial plans from $15/month | [open-meteo.com](https://open-meteo.com/)                                             | Alternative weather source, good for grid-based forecasts                                                |

**Recommendation**: Current weather adapter setup is sufficient; operationally, use `WEATHER_SOURCE` explicitly in deployments to choose simulated vs historical vs live.

#### Airport & Infrastructure Data

| Source               | What it provides                                         | Pricing                                              | Link                                                | Use for                                                                 |
| -------------------- | -------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------- | ----------------------------------------------------------------------- |
| **OurAirports**      | Airport layouts, runways, frequencies, navaids           | **Free** (community-maintained, open data)           | [ourairports.com](https://ourairports.com/)         | Integrated via **offline fixture generation** (not a live runtime feed) |
| **Eurocontrol DDR2** | European traffic demand data, airspace sectorisation     | **Free for research** (requires EUROCONTROL account) | [eurocontrol.int](https://www.eurocontrol.int/ddr)  | Network-level demand validation, European airspace context              |
| **BTS (US DOT)**     | On-time performance, passenger stats, T-100 traffic data | **Free** (US government, public domain)              | [transtats.bts.gov](https://www.transtats.bts.gov/) | Not yet integrated in runtime; target source for calibration pipelines  |

**Recommendation**: Add **BTS** ingestion for calibration next. This is still a gap in the current runtime.

#### Incident & Safety Data

| Source                                          | What it provides                                         | Pricing                                | Link                                                  | Use for                                                          |
| ----------------------------------------------- | -------------------------------------------------------- | -------------------------------------- | ----------------------------------------------------- | ---------------------------------------------------------------- |
| **FAA ASRS** (Aviation Safety Reporting System) | Voluntary incident reports from pilots, ATC, ground crew | **Free** (NASA-managed, public domain) | [asrs.arc.nasa.gov](https://asrs.arc.nasa.gov/)       | Not yet integrated; planned for incident probability calibration |
| **ICAO ADREP / ECCAIRS**                        | International accident/incident database                 | **Free** (registration required)       | [aviationreporting.eu](https://aviationreporting.eu/) | European incident data for more realistic event modelling        |

**Recommendation**: Implement an offline calibration pipeline using **FAA ASRS** before wiring incident priors into runtime.

#### Budget Summary

| Scenario                     | Monthly cost        | What you get                                                                                             |
| ---------------------------- | ------------------- | -------------------------------------------------------------------------------------------------------- |
| **Minimal** (free tier only) | **$0**              | adsb.lol positions + optional ADDS/IEM weather modes; BTS/ASRS calibration integration still to be built |
| **Recommended**              | **~$50/month**      | + Aviationstack Basic for real schedules and live flight status                                          |
| **Full**                     | **~$200–500/month** | + FlightAware AeroAPI for disruption stats, predictions, historical analysis                             |
| **Enterprise**               | **$5k+/year**       | + OAG schedules + FlightAware Premium with Foresight™ ML predictions                                     |

### 2.3 From Model-Driven to Prescriptive Digital Twin

The current system already has the building blocks (bottleneck detection, recommendation engine, what-if analysis). The shift is from **"here's what the model says would happen"** to **"here's what will happen based on real data, and here's what you should do about it"**.

#### What a prescriptive DT enables (business questions)

| Question                                                                  | Business value                                                                                 | What's needed                                                        |
| ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| "What happens if we add one more gate to Terminal B?"                     | **Capex justification** — quantify delay reduction vs construction cost                        | What-if engine + real passenger flow data                            |
| "Should we add a direct route to [new destination]?"                      | **Revenue decision** — projected passenger demand, gate utilisation impact, network effect     | Real OAG/BTS traffic demand + route profitability model              |
| "What if we had one more security lane?"                                  | **Staffing ROI** — quantify wait time reduction, connection risk reduction                     | Real passenger throughput data (BTS or airport-specific)             |
| "Where do connecting passengers go, and should we redesign the terminal?" | **Terminal planning** — optimise retail, gate proximity, walking distances                     | Real connection patterns from schedule data + passenger flow sensors |
| "If weather closes a runway for 2 hours, what's the best recovery plan?"  | **Operational cost savings** — minimise cascading delays, missed connections, diversions       | Real weather + real delay data + trained ML model                    |
| "Should we invest in a 3rd runway?"                                       | **Strategic capex** — the most expensive airport decision, modelled before committing billions | Full capacity model calibrated against real throughput               |

#### Tasks to get there

| #   | Task                              | Description                                                                                                                             | Depends on                                  |
| --- | --------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------- |
| 1   | **Data ingestion layer**          | Build a pluggable adapter system: each service can consume data from either simulation or real API, selectable at runtime               | Architecture solidification                 |
| 2   | **Model calibration**             | Use BTS on-time data + ASRS incidents to calibrate delay distributions, incident probabilities, passenger no-show rates against reality | Free data sources                           |
| 3   | **Scenario comparison framework** | Run the same scenario with simulated vs real data side-by-side, measure divergence, iteratively improve model fidelity                  | Tasks 1–2                                   |
| 4   | **Cost model integration**        | Attach financial cost to decisions: delay = $X/min, missed connection = $Y, diversion = $Z. Enable ROI calculations in recommendations  | Business input (cost data)                  |
| 5   | **Capacity planning mode**        | New what-if scenarios: add/remove gates, runways, security lanes, routes — measure impact on KPIs                                       | What-if engine (already built) + cost model |
| 6   | **ML prediction upgrade**         | Replace rule-based predictions with trained models (delay prediction, demand forecasting) using historical real data                    | FlightAware/BTS historical data             |
| 7   | **Decision audit trail**          | Log every recommendation, whether it was applied, and actual outcome — builds trust and enables model improvement                       | Already partially built (analysis_log)      |

---

## 3. Summary & Next Steps

| Priority        | Action                                                                   | Cost               | Timeline  |
| --------------- | ------------------------------------------------------------------------ | ------------------ | --------- |
| **Now**         | Integrate free data sources (BTS, ASRS, adsb.lol) to calibrate the model | $0                 | 2–3 weeks |
| **Short-term**  | Build pluggable data layer + subscribe to Aviationstack                  | ~$50/month         | 3–4 weeks |
| **Medium-term** | Add cost model, capacity planning scenarios                              | $0 (internal work) | 4–6 weeks |
| **If funded**   | FlightAware AeroAPI for ML predictions + OAG for schedules               | $200–500/month     | Ongoing   |

The digital twin already has the right architecture. The investment needed is primarily in **real data integration** and **business context** (cost models, capacity planning scenarios).
[text](../../ROADMAP.md)

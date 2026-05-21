# Use cases — Arthur International Airport Digital Twin

## Future project ideas for airport partnerships and research

This document captures use case ideas across six domains. Each is framed as a
concrete project proposal: what the problem is, what the twin provides, what
real data would be needed, and what the deliverable would look like.

---

## Domain 1 — Operations & safety

### 1.1 — Real-time runway incursion prevention

**Problem:** Runway incursions are one of the most dangerous events in aviation.
Most existing prevention systems are reactive (ground radar, ATC voice alert).
A digital twin can model the entire ground traffic picture — aircraft, vehicles,
personnel — and predict incursion risk before it materialises.

**What the twin provides:**

- Ground vehicle simulation already built (Phase 1.3 of ROADMAP2.md)
- Incident cascade engine already models runway incursion effects
- Real-time ADS-B integration planned (Phase 1.1)

**What a project would add:**

- Ingest real-time ADS-B + airport surface detection (ASDE-X or multilateration feed)
- Build a conflict prediction model: given current positions and clearances,
  compute probability of runway incursion in the next 60 seconds
- Visual alert system: highlight predicted conflict zones on the ground ops dashboard
  with colour-coded severity and countdown timer
- Train on historical ASRS (Aviation Safety Reporting System) incident database
  (free, NASA, https://asrs.arc.nasa.gov)

**Deliverable:** A runway incursion risk dashboard with live ADS-B feed, predictive
conflict detection (ML model), and alert integration into the existing incident service.

**Partnership value:** Directly applicable to any airport with a surface movement radar.
Could be demonstrated to airport safety officers as a proof of concept for
AI-assisted runway safety systems.

---

### 1.2 — Emergency response simulation and training

**Problem:** Airport emergency response drills (aircraft crash, fire, medical mass casualty)
are expensive, disruptive, and infrequent. A digital twin can run unlimited simulated
emergencies and train response teams on optimal resource deployment.

**What the twin provides:**

- Incident engine with emergency protocols already built
- Ground vehicle simulation (fire trucks, medical units as vehicle types)
- Full terminal and airfield layout

**What a project would add:**

- Emergency vehicle routing: shortest path from depot to incident location using
  the spatial layout model
- Response time simulation: given N vehicles and M depots, optimise placement
  to minimise average response time (classic facility location problem)
- Tabletop exercise mode: pause the simulation at incident injection, let the
  trainee decide the response, then resume and measure outcomes vs optimal
- Training scenario library: ICAO Annex 14 emergency categories (aircraft accident,
  bomb threat, medical, fire) each as a YAML scenario

**Deliverable:** An emergency response training module with scenario injection,
response time measurement, and a post-exercise report comparing the trainee's
decisions against the model's optimal response.

**Data source:** ICAO Annex 14, Chapter 9 (rescue and firefighting) — public standard.

---

### 1.3 — Airfield maintenance scheduling optimiser

**Problem:** Runways and taxiways require regular maintenance (rubber removal,
line repainting, surface inspection). Scheduling this maintenance involves closing
parts of the airfield, which impacts capacity. Currently scheduled on fixed cycles,
not on actual condition or traffic impact.

**What the twin provides:**

- Full airfield layout and runway capacity model
- Traffic simulation at different capacity levels
- Cost model (delay cost per hour of reduced capacity)

**What a project would add:**

- Pavement condition index (PCI) model: simulate degradation over time as a
  function of traffic volume (movements × aircraft weight)
- Maintenance window optimiser: find the maintenance schedule that minimises
  total cost (delay cost during maintenance + long-term cost of deferred maintenance)
- What-if scenarios: "what if we defer runway 09L maintenance by 3 months?" →
  project cost of increased degradation vs delay cost avoided
- Visualise maintenance impact on the planning dashboard

**Deliverable:** A maintenance scheduling tool integrated into the capacity planning
service, with a pavement degradation model and cost-optimal scheduling recommendations.

---

## Domain 2 — Capacity & planning

### 2.1 — Slot allocation and coordination simulator

**Problem:** Level 3 coordinated airports allocate departure and arrival slots to
airlines. When demand exceeds capacity, slot allocation is a complex optimisation
problem with significant financial stakes. Currently handled manually or with
expensive proprietary tools.

**What the twin provides:**

- Full schedule model with flight-level capacity constraints
- Runway capacity model (weather + aircraft type dependent)
- Gate assignment logic

**What a project would add:**

- Slot allocation engine: given demand requests and capacity constraints, compute
  an optimal allocation minimising total delay while respecting airline preferences
- Schedule compression: identify slots that can be moved by ±15 min to improve
  overall throughput without violating airline constraints
- Slot trading simulation: model the secondary market where airlines trade slots,
  assess the welfare impact of different trading rules
- Integration with IATA season schedule data (available for research via IATA)

**Deliverable:** A slot coordination module demonstrating optimal allocation under
different demand and capacity scenarios, with a visualisation of the resulting
schedule and comparison against a first-come-first-served baseline.

---

### 2.2 — Terminal design A/B testing

**Problem:** Terminal layouts — gate positions, retail placement, security checkpoint
design — are designed by architects with limited ability to test their impact on
passenger flow before construction. A digital twin can simulate different layouts
and measure outcomes before a single wall is built.

**What the twin provides:**

- Physical layout model with gate positions and zone distances (Gap 1)
- Passenger flow simulation with walking times
- Retail revenue model (dwell time × spend rate)
- Connection risk model (MCT dependent on walking distance)

**What a project would add:**

- Layout variant A/B testing: define two terminal configurations as `InfrastructureConfig`
  variants and compare passenger KPIs (average walking time, missed connections,
  retail exposure, boarding delay)
- Heatmap comparison: side-by-side passenger density heatmaps for each layout variant
- Retail placement optimiser: given a fixed terminal footprint, where should retail
  be placed to maximise dwell-time exposure for the most valuable passenger segments
  (long-haul, connecting)?
- Accessibility score: what fraction of passengers with special assistance needs
  can reach their gate within their allotted time under each layout?

**Deliverable:** A terminal design testing tool that takes two GeoJSON layout files
and produces a comparative report across 10 KPIs with statistical significance testing.

---

### 2.3 — Network resilience and hub dependency analysis

**Problem:** Airports that rely heavily on one or two hub carriers are exposed to
network disruptions. When a hub carrier reduces service, the airport can lose 30–40%
of movements. Understanding this dependency and planning resilience routes is a
strategic priority.

**What the twin provides:**

- Multi-airport network model (Phase 3 of ROADMAP2.md)
- Route profitability model
- Demand forecasting with BTS T-100 data

**What a project would add:**

- Hub dependency score: for each airline at KART, compute the fraction of total
  movements, revenue, and connecting passengers they represent
- Disruption simulation: remove a hub carrier's flights and measure the cascade
  impact on total pax, gate utilisation, and financial performance
- Resilience routing: identify which routes from the OurAirports destination pool
  would best diversify KART's traffic mix and reduce hub dependency
- Network gravity model: estimate catchment area demand for each potential new route
  using city population, GDP, and existing traffic patterns (public World Bank data)

**Deliverable:** A network resilience report generator that scores current dependency
and recommends a 5-route diversification plan with projected demand and revenue impact.

---

## Domain 3 — Sustainability

### 3.1 — Carbon footprint tracker and reduction optimiser

**Problem:** Airports are under increasing pressure to report and reduce Scope 1, 2,
and 3 emissions. Ground operations (APU use, ground vehicles, terminal energy) are
Scope 1. Connecting flights are Scope 3. Currently tracked manually with large
estimation uncertainty.

**What the twin provides:**

- Ground vehicle simulation (fuel consumption per dispatch)
- Turnaround task graph (APU runtime per aircraft)
- Passenger flow (terminal energy proportional to pax count)
- Full flight schedule with aircraft types and distances

**What a project would add:**

- APU emission model: aircraft on stand running APU emit ~3 kg CO₂/min.
  Turnaround task graph already tracks stand time — multiply by APU emission factor
  and aircraft type. Push aircraft to use ground power (GPU) instead: model the
  switch and compute emission reduction.
- Ground vehicle emissions: fuel consumption per vehicle type per km dispatched.
  Electrification scenario: replace diesel fleet with EV and show emission reduction.
- Terminal energy model: kWh per pax per hour (from ACI Airport Carbon Accreditation
  benchmarks — free). Seasonal variation, night mode savings.
- Scope 3 reporting: distance × pax × emission factor per flight (ICAO Carbon
  Emissions Calculator methodology — public).
- Net zero trajectory: given a carbon budget target and timeline, what combination
  of interventions (GPU adoption, EV fleet, solar panels, fuel efficiency) reaches it?

**Data sources:**

- ICAO Carbon Emissions Calculator: https://www.icao.int/environmental-protection/CarbonOffset
- ACI Airport Carbon Accreditation: https://airportcarbonaccreditation.org
- IPCC emission factors: public

**Deliverable:** A carbon dashboard with real-time CO₂ tracking by source category,
a net-zero scenario builder, and an annual carbon report generator.

---

### 3.2 — Noise impact simulation

**Problem:** Airport noise is a major community relations and regulatory challenge.
Different runway configurations, departure procedures, and curfew policies create
very different noise contours. Simulating noise impact before implementing operational
changes would help airports manage community relations proactively.

**What the twin provides:**

- Full flight schedule with aircraft types and runway assignments
- Runway direction and heading model
- Time-of-day distribution of movements

**What a project would add:**

- Noise contour model: for each departure/arrival event, compute a simplified
  noise footprint based on aircraft type, thrust setting, and distance from runway.
  ICAO Doc 9911 provides the methodology (public).
- Community impact score: overlay noise contours on a population grid (OpenStreetMap
  building footprints + census population data) to count affected residents
- Operational scenario comparison: which runway configuration, curfew time, and
  departure procedure produces the smallest community impact?
- Noise budget tracker: many airports operate under annual noise quota systems
  (ICAO Chapter 14 compliance). Track quota usage in real time as the simulation runs.

**Data sources:**

- OpenStreetMap building footprints: free, ODbL
- US Census population grid: free, public domain
- ICAO Doc 9911 (noise abatement): https://store.icao.int

**Deliverable:** A noise impact dashboard showing real-time noise contours,
a community exposure score per runway configuration, and a noise budget tracker.

---

### 3.3 — Energy consumption optimisation

**Problem:** Airport terminals are large energy consumers. HVAC, lighting, escalators,
conveyors, and IT systems all respond to passenger load — but most airports run
systems at full capacity regardless of occupancy. Demand-responsive energy management
could reduce costs by 15–25%.

**What the twin provides:**

- Passenger zone occupancy by hour (zone density model)
- Baggage conveyor activity (throughput per zone)
- Terminal floor plan (size of each HVAC zone)

**What a project would add:**

- Energy demand model: kWh per zone per hour as a function of occupancy.
  Parametrised from ACI benchmarks.
- Predictive HVAC scheduling: use the LightGBM passenger forecast to pre-heat/cool
  zones 30 minutes before peak occupancy rather than reactively
- Conveyor idle scheduling: when a make-up zone is empty and no flights are
  assigned for the next 20 minutes, shut it down. Show energy and cost saved.
- Renewable integration: model a solar array on the terminal roof (kWp × irradiance
  factor × efficiency) and show the offset against terminal consumption.

**Deliverable:** An energy management dashboard with real-time consumption by zone,
a predictive scheduling engine, and an annual energy cost and carbon report.

---

## Domain 4 — Passenger experience

### 4.1 — Personalised wayfinding and disruption notification

**Problem:** When a flight is delayed or gate is changed, many passengers miss the
update because they are shopping, eating, or in a lounge. Proactive, location-aware
notification could significantly reduce late boardings and missed connections.

**What the twin provides:**

- Passenger location model (current zone per passenger)
- Gate change and delay event stream (Kafka)
- Connection risk scoring (already built)
- Walking time model from any zone to any gate

**What a project would add:**

- Personalised urgency model: for each passenger, compute the urgency of a gate
  change notification based on their current location and time to boarding cutoff.
  A passenger at gate B07 who just moved to gate C12 needs an immediate alert.
  A passenger already at C12 does not.
- Optimal notification timing: notify the passenger exactly when they need to
  start walking — not before (alert fatigue) and not after (too late). Computed
  from `time_to_departure - walking_time_to_new_gate - 5_min_boarding_buffer`.
- Multi-channel simulation: test different notification channels (in-app, SMS,
  boarding pass scan trigger, airport PA) and compare late boarding rates.
- Accessibility routing: passengers with mobility impairments receive adjusted
  walking times and alternative routes (lifts vs escalators).

**Deliverable:** A passenger notification simulation module that measures late
boarding rates under different notification strategies and recommends the optimal
trigger timing model.

---

### 4.2 — Retail and F&B revenue optimisation

**Problem:** Airport retail generates 35–50% of airport revenue but is poorly
targeted. Shops and restaurants are positioned at design time based on gut feel
and benchmark data, not on actual passenger flow patterns and dwell time analysis.

**What the twin provides:**

- Passenger flow simulation with dwell times
- Zone occupancy by hour and passenger segment
- Retail revenue model (dwell time × spend rate per segment)
- Connection passenger identification

**What a project would add:**

- Passenger segmentation: classify passengers by flight type (domestic, long-haul,
  connecting) and time of day. Each segment has different retail spend propensity.
- Revenue attribution: for each retail zone, compute how much revenue is generated
  by passengers whose natural walk path passes through it vs passengers who detour.
- Placement optimiser: given N retail units and a fixed floor plan, find the
  assignment of shop types to locations that maximises total expected revenue.
  Uses the passenger flow as a demand signal.
- Dynamic pricing simulation: model time-of-day pricing for F&B (higher margins
  during peak, lower during off-peak) and compute revenue impact.

**Deliverable:** A retail analytics module showing revenue attribution by zone,
a placement optimiser with expected revenue uplift, and a scenario comparison
between current layout and optimised layout.

---

### 4.3 — Accessibility and special assistance optimisation

**Problem:** Passengers requiring special assistance (wheelchair users, unaccompanied
minors, medical cases) consume disproportionate resource and are frequently late to
gate. The current model handles them with a simple bypass — a real model would
reflect the operational complexity.

**What the twin provides:**

- `special_assistance` flag on passenger nodes
- Dedicated SA security lane model
- Walking time model with ×2.5 multiplier

**What a project would add:**

- Wheelchair resource model: N wheelchairs available per terminal, dispatched from
  a depot. Queue builds when demand exceeds supply.
- Escort routing: plan the optimal path for a wheelchair escort from check-in to
  gate, accounting for lift availability, queue build-up at security, and gate
  distance.
- SLA tracking: what fraction of SA passengers board before door close? What is
  the mean time from check-in to gate? Benchmark against ECAC Doc 30 service
  standards (public).
- Staffing recommendation: how many wheelchair agents are needed per terminal per
  peak hour to meet the SLA target?

**Deliverable:** An accessibility operations module with resource dispatching,
SLA tracking, and staffing recommendations per terminal per hour.

---

## Domain 5 — AI & research

### 5.1 — Multi-agent reinforcement learning for airport operations

**Problem:** Airport operations involve multiple independent agents (airlines, handlers,
ATC, airport ops) each optimising their own objectives. The global optimum (minimum
total delay, maximum throughput) is not achievable by any single agent acting alone.
Multi-agent RL can learn cooperative policies that approximate the global optimum.

**What the twin provides:**

- A complete simulation environment (perfect for RL training)
- `gymnasium` wrapper already planned (Phase 5.1 of ROADMAP2.md)
- Well-defined reward signal (delay minutes, EU261 liability, throughput)

**What a project would add:**

- Multi-agent framework: separate agents for airline (gate requests, pushback timing),
  handler (vehicle dispatch, baggage priority), and airport ops (security lane management,
  runway assignment). Each agent has its own observation space and action space.
- Competitive vs cooperative training: compare MARL policies trained to maximise
  individual objectives vs policies trained with a shared global reward.
- Interpretability: after training, extract the learned policies as decision trees
  (CART) so they can be explained to airport operations staff.
- Transfer learning: train on KART, evaluate on a different airport config.
  Does the policy generalise?

**Research value:** A publishable contribution to the applied MARL literature,
with a reproducible environment that other researchers can use (the open-source
twin as a benchmark).

---

### 5.2 — LLM-powered air traffic communication analysis

**Problem:** ATC voice communications are recorded at every airport but rarely
analysed systematically. They contain rich operational intelligence: patterns in
controller workload, non-standard phraseology that precedes incidents, handoff
friction between sectors.

**What the twin provides:**

- Simulated ATC context (active flights, runway states, weather) at every sim-minute
- Incident event timeline as ground truth for correlation analysis

**What a project would add:**

- Synthetic ATC transcript generator: given the current simulation state, generate
  realistic ATC communications using an LLM prompted with current traffic picture.
  Produces a labelled dataset for research without using real recordings.
- Workload classification: classify each controller utterance by cognitive load
  indicator (number of simultaneous aircraft, weather state, incident active).
- Non-standard phraseology detector: fine-tune a classifier to identify deviations
  from ICAO standard phraseology in synthetic transcripts.
- Incident correlation: do non-standard phraseology events in the synthetic data
  correlate with incident occurrence in the simulation? Validate the hypothesis.

**Data sources:**

- ASRS Aviation Safety Reports (free, NASA) — real non-standard phraseology examples
- ICAO Doc 9432 Manual of Radiotelephony — public standard

**Research value:** A synthetic ATC dataset generator and a workload analysis
pipeline, both relying only on open-source tools and the KART simulation.

---

### 5.3 — Counterfactual delay analysis

**Problem:** After a major disruption (storm, incident, system failure), operations
teams want to know: "Could we have done better? What if we had started the ground
delay program 30 minutes earlier?" Counterfactual analysis on live operational data
is hard because the counterfactual never happened.

**What the twin provides:**

- Full simulation replay from any snapshot
- What-if engine (shadow simulation)
- Decision audit trail (recommendation log)

**What a project would add:**

- Disruption replay: load a historical disruption snapshot (or a scenario result)
  and replay it with different decision timing
- Causal graph: model the causal chain from initial event through interventions
  to final delay outcome using a directed acyclic graph (DAG). Identify the
  intervention with the highest causal impact.
- Counterfactual report generator: "had the GDP been initiated at T+10 instead of
  T+45, total delay would have been 23% lower and EU261 liability would have been
  reduced by €41,000"
- Learning loop: compare counterfactual outcomes across many simulated disruptions
  to identify systematic decision biases (operators consistently intervene too late
  on weather events, too early on security events)

**Research value:** A methodology for counterfactual operational analysis, applicable
to any domain with a simulation environment and a decision log.

---

## Domain 6 — Business & finance

### 6.1 — Airport valuation model

**Problem:** Airport valuations for M&A, concession contracts, and infrastructure
funds rely on DCF models built in spreadsheets with simplified assumptions about
capacity, demand growth, and operational costs. A digital twin can produce a
physics-grounded financial model rather than a spreadsheet extrapolation.

**What the twin provides:**

- Full cost model (ROADMAP_COST.md)
- Capacity planning with NPV/IRR (ROADMAP_PLANNING.md)
- Demand growth model (Eurocontrol STATFOR)

**What a project would add:**

- Revenue waterfall model: landing fees + passenger charges + retail + parking +
  cargo + slot fees, all as functions of traffic volume
- EBITDA simulation: revenue minus staffing, energy, maintenance, and incident
  costs — all already in the cost model
- Sensitivity analysis: how does EBITDA change under low/base/high demand growth,
  different fuel prices, different EU261 claim rates?
- Comparable transaction benchmarks: use public ACI data on airport revenue per pax
  to sanity-check the model output
- Investment thesis generator: given a proposed capex programme (new runway, terminal
  extension), auto-generate the investment thesis narrative with supporting KPIs

**Deliverable:** A financial model PDF generator that takes a planning scenario result
and produces a 5-page investment case document with NPV waterfall, sensitivity tables,
and risk factors.

---

### 6.2 — Airline negotiation simulation

**Problem:** Airport-airline commercial negotiations (landing fees, slot allocations,
gate leases) are opaque and adversarial. Neither side has a good model of how their
counterpart's operations would be affected by different contract terms.

**What the twin provides:**

- Per-flight cost breakdown (landing fee, gate fee, handling)
- Delay cost model (EU261, crew overtime)
- Route profitability model

**What a project would add:**

- Airline P&L per route: for each airline at KART, compute their full cost per
  rotation (landing + gate + handling + delay exposure) against estimated ticket
  revenue (average fare × load factor × seats)
- Fee sensitivity analysis: "if landing fees increase by 15%, which airlines are
  at risk of reducing frequencies or withdrawing routes?"
- Negotiation game: model a bilateral negotiation between KART and its top airline.
  Each party has a private valuation (reservation price). Find the Nash equilibrium
  contract terms.
- Volume discount modelling: test different volume discount structures and show
  their revenue and traffic impact

**Deliverable:** An airline commercial analytics module showing per-route profitability
for each airline and a fee sensitivity report.

---

### 6.3 — Insurance and risk modelling

**Problem:** Airport liability insurance (hull damage, passenger disruption, third-party
liability) is priced using historical actuarial tables that don't reflect the specific
operational risk profile of individual airports. A digital twin that can quantify
risk distributions would allow more accurate risk transfer pricing.

**What the twin provides:**

- Monte Carlo incident simulation (frequency and severity)
- EU261 liability model (exact statutory amounts)
- Incident cost model (direct + response + cascade)

**What a project would add:**

- Annual loss distribution: run 1,000 simulated years at compressed speed. For each
  year, record total incident cost, total EU261 liability, and total cascade cost.
  Fit a loss distribution (log-normal or Pareto) to the results.
- Value at Risk (VaR): compute the 95th and 99th percentile annual loss — the
  amount the airport should retain as a self-insurance reserve.
- Risk reduction credit: compare VaR with and without specific mitigations
  (better ground vehicle tracking, faster weather response, additional runway capacity).
  Show how much each mitigation reduces the 99th percentile loss.
- Reinsurance layer optimisation: given the fitted loss distribution, find the
  optimal retention level and reinsurance attachment point that minimises total
  cost of risk.

**Deliverable:** An actuarial risk report showing the annual loss distribution,
VaR at 95/99th percentile, and a risk mitigation ROI table.

---

## Approaching airports as partners

These use cases are structured to be proposable to airport operators, airlines,
and research institutions. Here is a practical engagement framework:

### What to offer

| What you bring                        | What they bring                        |
| ------------------------------------- | -------------------------------------- |
| Open-source simulation platform       | Domain expertise and operational data  |
| ML models and optimisation algorithms | Validation of model assumptions        |
| Reproducible scenarios and reporting  | Feedback on which KPIs actually matter |
| A published methodology               | A real deployment case study           |

### Which use cases require real data

| Use case                      | Fully synthetic (no real data needed) | Requires real data           |
| ----------------------------- | ------------------------------------- | ---------------------------- |
| Emergency response training   | ✅                                    |                              |
| Terminal design A/B testing   | ✅                                    |                              |
| Retail placement optimiser    | ✅                                    |                              |
| Multi-agent RL benchmark      | ✅                                    |                              |
| Carbon tracker                | ✅ (free emission factors)            |                              |
| Slot allocation simulator     | ✅                                    |                              |
| Runway incursion prevention   |                                       | ADS-B + surface radar feed   |
| Network resilience analysis   |                                       | BTS T-100 (free)             |
| Noise impact simulation       |                                       | Aircraft performance tables  |
| Airport valuation model       |                                       | Airport financial statements |
| Counterfactual delay analysis |                                       | Operational incident logs    |

### Lowest friction starting points

The three use cases most likely to result in a concrete partnership or publication
with minimal data access friction:

1. **Multi-agent RL benchmark** — fully synthetic, clear research contribution,
   publishable at NeurIPS/ICML/AAMAS. The twin is the environment.

2. **Terminal design A/B testing** — no operational data needed, direct business
   value for any airport planning a renovation, and the GeoJSON layout model
   already exists in the codebase.

3. **Carbon footprint tracker** — free emission factors, clear regulatory driver
   (CORSIA, EU ETS), and every airport in the world needs this. Could be positioned
   as a free open-source carbon reporting tool that happens to be built on the twin.

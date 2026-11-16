# IMPORTANT FOR SUBMISSION

Pre-submission audit of the EVSK airport digital twin: service coverage, fidelity
gaps, and an audit of the machine-learning and data pipelines.

Findings are recorded with `file:line` evidence so each can be verified
independently. Severity:

| Level | Meaning |
| ----- | ------- |
| **P1** | Invalidates a reported result. Must be fixed before any metric is quoted. |
| **P2** | Correctness or contract defect. Fix before submission. |
| **P3** | Coverage or documentation gap. Fix before submission if cheap. |

Scope: this document is about the system. It makes no claims about, and no
recommendations for, any manuscript.

---

## 1. Method

Read-only inspection of the repository at the current working tree. Every finding
below was confirmed by reading the cited code, not inferred from documentation.
Where a specification and the code disagree, both are quoted.

Reference points used for "what should be true":

- `AGENTS.md` — project hard rules and stack
- `docs/architecture/EVENT_BUS.md` — topic contracts
- `docs/architecture/DATA_SOURCES.md` — adapter interface
- `docs/roadmaps/ROADMAP3.md`, `docs/roadmaps/ROADMAP4.md` — the written plan for
  the planning-service models
- `docs/services/*/SPEC.md` — per-service contracts

---

## 2. Service coverage audit

Ten service directories: nine domain services plus the API gateway.

| Service | Layer | `SPEC.md` | `SKILL.md` | In `ROUTES.md` |
| ------- | ----- | --------- | ---------- | -------------- |
| analysis-service | L3 | **absent** | **absent** | yes |
| planning-service | L3 | yes | **absent** | **absent** |
| cost-service | L0/L3 | yes | yes | **absent** |
| flight-service | L0 | yes | yes | yes |
| passenger-service | L0 | yes | yes | yes |
| baggage-service | L0 | yes | yes | yes |
| weather-service | L0 | yes | yes | yes |
| incident-service | L0 | yes | yes | yes |
| sim-orchestrator | L0 | yes | yes | yes |
| api-gateway | — | yes | yes | yes |

`docs/services/` contains nine `SPEC.md` files, but `analysis-service` has no
directory under it. `docs/architecture/ROUTES.md` has 84 documented routes across
seven services and the gateway; `cost-service` and `planning-service` have no
section at all.

### 2.1 P2 — The L3 service is the least specified

`analysis-service` carries anomaly detection, the bottleneck detectors, the
recommender, the what-if engine, the approval queue, autonomous mode, the MILP
slot allocator and the NLP layer. It has neither a specification nor a skill
file. `planning-service` has a specification but no skill file.

This is the wrong way round for a system whose central claim is
specification-first development: the two services realising the decisional layer
are the two least documented. It also explains, rather than compounds, the
finding that models can report success without having trained.

### 2.2 P2 — Two of nine domain services are absent from the route catalogue

`ROUTES.md` documents `flights.commands` consumers but omits the endpoint
surface of `cost-service` and `planning-service` entirely. The planning models
are reachable only through the gateway's passthrough mount
(`services/api-gateway/src/proxy.ts:163-165`), so their routes are specified
only in code.

---

## 3. Fidelity gaps

### 3.1 L0 — the forecaster writes back, and only into service rate

The LightGBM queue forecaster in `passenger-service` is the only learned model
whose output re-enters the simulation. The mechanism is narrower than a generic
"feeds back into state":

```
kafka/consumer.py:1448   _ml_tick(sim_time)
kafka/consumer.py:1016   _get_forecast_queues(sim_time)   # predict() per terminal
kafka/consumer.py:938    _drain_security_queues(...)     # called from the tick at :651
services/security.py:100  drain(forecast_queue, delta_minutes)
services/security.py:67   drain_per_tick(forecast_queue, delta_minutes)
services/security.py:41   effective_throughput(forecast_queue)
```

`effective_throughput` compares the observed queue depth against the forecast. If
`forecast > 0` and `queue_depth > forecast * 1.3`, throughput is scaled by
`clamp(forecast / queue_depth, 0.5, 1.0)` against a base of
`lanes_open * 180` pax/hr (`services/security.py:11-12`). It therefore sets the
security checkpoint's per-tick drain rate. It sets no generation parameter and no
staffing level.

A second path carries the forecast's influence further. `wait_minutes(forecast)`
(`security.py:60`) is what `kafka/consumer.py:676` passes to
`ml/congestion.py:15`, which after five consecutive ticks above 20 minutes emits
`SecurityCongestionDetected`. That event is what triggers the analysis-service
bottleneck detectors. The forecaster thus reaches the decisional layer
indirectly, by fact on the bus, not by import.

Other L0 characteristics, all confirmed:

- 12 features, `services/passenger-service/ml/features.py:11-24`
- `LGBMRegressor`, 200 estimators, depth 6, `ml/training.py:38-53`
- retrain every 3 simulated days, minimum 500 rows, `ml/training.py:24-25`
- temporal split 80/20 with MAE reported, `ml/training.py:129-133`
- day-1 fallback `expected_pax_next_90min * 0.35`, `ml/inference.py:19,72`

### 3.2 L2 — two adapter mechanisms, not one contract

There are two independent adapter systems.

**Shared registry.** `services/_common/data_sources.py` provides
`DataSourceRegistry`, the `DataSourceAdapter` protocol and `SimulatedSourceAdapter`,
as described in `docs/architecture/DATA_SOURCES.md:48-54`. It has exactly three
importers:

```
services/sim-orchestrator/services/injector.py
services/weather-service/kafka/consumer.py
services/passenger-service/kafka/consumer.py
```

**Local factory.** `services/planning-service/adapters/registry.py` is a separate
mechanism with a different shape: `get_schedule_adapter` (`:37`),
`get_weather_adapter` (`:65`), `get_demand_adapter` (`:91`), `list_available_adapters`
(`:123`). It has no `register`/`switch` and no runtime source switching; the source
is chosen per call and wrapped in a `BTSAdapter` that exposes `is_real_data`.
Consumers are `scenarios/runner.py:269,275` and `routers/planning.py:39,57,76`.

Consequence: an L2→L3 contract exists for the scenario engine, and a raw file
read exists beside it in the same service. See §4.6.

### 3.3 L2 — BTS provenance as actually implemented

The reference data is real, filtered and anonymised at airport level.

`scripts/helper_filter_bts_data.py` takes the genuine 18,227-row
`data/bts/T100_2026.csv` and writes a 555-row `data/bts/T100_reference.csv`. Per
its own docstring it keeps only scheduled service classes (`F`/`L`/`P`), drops
zero-passenger rows, and remaps the reference airport's IATA code to `ART`. The
default reference airport is `BOS` (`--reference-airport`, `:199`); candidates
listed are BOS, IAD, SAN, RDU, STL, BNA, MKE, CLT.

The filtered file is mounted read-only and consumed by four call sites:

```
docker-compose.yml:193  PASSENGER_BTS_FILE  -> passenger-service
docker-compose.yml:323  BTS_CSV_PATH        -> planning-service
services/sim-orchestrator/services/bts_calibration.py:31,106
services/passenger-service/kafka/consumer.py:169,204
services/planning-service/ml/training_pipeline.py:17
services/planning-service/adapters/registry.py:33
services/planning-service/engine/network.py:148
```

Calibration is the real data-source refinement, and it is deterministic. Per
`sim-orchestrator/services/bts_calibration.py` docstring it "directly
calibrat[es] the simulation's schedule generation and passenger models":
`DEPARTURES_PERFORMED` supplies route frequency weights replacing uniform
destination sampling, and `PASSENGERS/SEATS` supplies per-route load factors
replacing the global Beta(8, 2) draw, with seasonal adjustment and ±2.5% seeded
noise (`passengers.py:80-85`). No learned model participates.

### 3.4 L3 — the loop is wired for one of three command topics

| Command topic | Subscriber | Producer |
| ------------- | ----------- | -------- |
| `flights.commands` | `flight-service/kafka/consumer.py:294`, handler `:419` | `analysis-service/kafka/producer.py:19,167` |
| `passengers.commands` | `passenger-service/kafka/consumer.py:367` | **none** |
| `baggage.commands` | `baggage-service/kafka/consumer.py:193` | **none** |

`EVENT_BUS.md:33-34,53-54` documents all three as analysis-service producers, with
3 and 6 supported command types respectively. No service publishes to
`passengers.commands` or `baggage.commands`. Both consumer-side validators exist
(`passenger-service/application/commands.py`,
`baggage-service/application/commands.py`), so the receiving path is ready and
only the publishing side is missing.

### 3.5 L3 — three of fourteen action types can become commands

The recommender produces 14 `ActionType` values
(`analysis-service/models/domain.py:57-71`). `to_flight_command`
(`approval_queue.py:189-221`) maps only:

- `reassign_gate` → `ReassignGate`, requires `flight_id` + `gate_id`
- `hold_connecting_flight` → `HoldFlight`, requires `flight_id` + duration
- `delay_taxi` → `HoldFlight`, requires `flight_id` + duration

The other 11 return `None` and the approved proposal is recorded as a fact only
(`routers/analysis.py:203-217`). The function's own docstring calls this "the
honest seam": a command is formed only when a concrete flight is named, so
terminal-level and aggregate recommendations map to nothing. This is a defensible
design, but it means the actionability rung is currently reachable for 3 of 14
action types, on 1 of 3 topics.

### 3.6 L3 — the RL policy is not shipped

`analysis-service/services/rl/agent.py:22-24` loads
`models/rl_policy.zip`. `services/analysis-service/models/` contains only
`domain.py` and `__init__.py`. With no policy present, `autonomous.py:355-360`
fails to load and the agent degrades to the rule-based path
(`rl/agent.py:68`, `no_action`). The training entry points exist
(`training/train_rl.py`, `training/benchmark_rl.py`) but no artefact is
distributed, so this capability is a code path rather than a deployed feature.

### 3.7 P3 — documentation drift on the ML inventory

`docs/dashboards/ML.md` claims to "describe all ML/AI features integrated into the
airport digital twin" and documents "four distinct ML/AI subsystems plus a
rule-based prescriptive layer": LightGBM queue forecasting, RL, Isolation Forest
anomaly detection, the NLP interface, and the prescriptive layer. It does not
mention the planning-service demand regressor or delay classifier. `ML.md` also predates the current training cadence in
`docs/skills/forecasting.SKILL.md`, which correctly states the 3-simulated-day
retrain interval at `:188`.

---

## 4. Pipeline defects

The planning-service models are the subject. Both are trained by
`services/planning-service/ml/training_pipeline.py` and served read-only from
`routers/planning.py` (`:563,589` demand, `:733` delay).

Neither model is called by the scenario engine. `rg` for `get_demand_model`,
`get_delay_model` and `predicted_daily_pax` across `services/planning-service/engine/`
and `services/planning-service/scenarios/` returns nothing. Both reach consumers
only through their REST handlers.

### 4.1 P1 — delay labels are a rule, not observations

`build_delay_training_data` (`training_pipeline.py:65`) documents itself
accurately:

```
66:  """Build synthetic delay training_data from BTS load factors.
68:  Real delay data would come from BTS On-Time Performance dataset.
69:  This generates approximate labels from load factors and seasonal patterns.
```

The label is a two-clause threshold on load factor and month:

```
91:  peak_month = month in (6, 7, 8, 12)
92:  was_delayed = 1 if (lf > 0.85 and peak_month) or lf > 0.95 else 0
```

BTS load factors are therefore used to *construct* the supervision signal, not to
correlate with it. The reported AUC measures how well LightGBM recovers a
hand-written threshold. This is drift from a written specification:
`ROADMAP4.md:977` states "Use BTS historical on-time data as training labels."

**Fix.** Ingest BTS On-Time Performance. `ROADMAP3.md:1007-1010` gives the source
(`https://www.transtats.bts.gov/DL_SelectFields.aspx?gnoyr_VQ=FGJ`) and
`:1116` lists it as public domain under Task 9.1. Build observed labels from
`ARR_DELAY15` / `DEP_DELAY15` for the same remapped route set.

**Verify.** Assert the label column is present in the input CSV and that
`P(label == 1)` is neither 0 nor 1.

### 4.2 P1 — the delay target leaks into a feature

```
103:  "historical_otp": 1.0 - (0.15 if was_delayed else 0.05),
```

`historical_otp` is computed from the label. The model receives a transformed copy
of its own target as an input.

**Fix.** Remove `historical_otp` from `DELAY_FEATURES`
(`delay_model.py:17-26`). If historical on-time performance is to remain a
feature, source it from the preceding period rather than from the row being
labelled.

**Verify.** No column in the built training set may be a function of the label.

### 4.3 P1 — the demand target is duplicated into a feature

```
42:  daily_pax = pax / 30
...
50:  "historical_avg_pax": daily_pax,
53:  "actual_pax": daily_pax,
```

Feature and target are the same number. MAE and RMSE are therefore near zero by
construction and measure nothing.

**Fix.** Populate `historical_avg_pax` from the *previous* month for the same
route, not the current row. T-100 is monthly, so this is available by grouping on
`(ORIGIN, DEST)` and shifting.

**Verify.** `assert not df["historical_avg_pax"].equals(df["actual_pax"])`, and
assert the feature leads the target by at least one period.

### 4.4 P1 — constant features

Delay model, 4 of 8 features are literals (`:97-99` plus sampled hours):
`day_of_week: 2`, `weather_category: 0`, `aircraft_type_code: 0`,
`flights_prev_2h: 20`. Only `hour` varies, over four values.

Demand model, 4 of 7 features are literals (`:47-52`): `day_of_week: 2`,
`is_holiday: 0`, `growth_trend: 0.034`, `is_hub_connection: 0`.

**Fix.** Remove them from the feature lists, or vary them in the builders where a
real source exists. Note that T-100 is a monthly aggregate, so `day_of_week`
*cannot* be sourced at all and must be dropped from both training and inference
rather than synthesised.

**Verify.** Assert `df[FEATURE_COLS].nunique().min() > 1` for every feature
column, allowing documented exceptions.

### 4.5 P2 — train/serve skew

`demand_model.py` computes at inference what the builder fixes at training:

| Feature | Training (`training_pipeline.py`) | Inference (`demand_model.py`) |
| ------- | ------------------------------- | ----------------------------- |
| `day_of_week` | always `2` (`:47`) | `forecast_date.weekday()` (`:153`) |
| `is_holiday` | always `0` (`:48`) | holiday lookup (`:154`) |
| `is_hub_connection` | always `0` (`:52`) | caller argument `is_hub` (`:149`) |
| `growth_trend` | `0.034` (`:51`) | `0.034` (`:156`) |

The model is therefore trained on a distribution it never sees at inference.
`delay_model.py:101-111` has the same shape, with defaults supplied for
`aircraft_type_code`, `flights_prev_2h`, `distance_km` and `historical_otp`.

**Fix.** Derive each feature from one shared function used by both paths, and drop
any feature that cannot be populated identically in both.

### 4.6 P2 — training reads the reference CSV directly, bypassing the adapter

`training_pipeline.py` imports only `csv`, `pathlib` and `structlog` (`:8-13`). It
opens the file directly:

```
17:  DEFAULT_BTS_PATH = "/app/data/bts/T100_reference.csv"
29:  with open(path, ...) as f:      # demand builder
77:  with open(path, ...) as f:      # delay builder
```

It imports neither `_common.data_sources` nor `adapters.registry`, despite
`adapters.registry.get_demand_adapter` (`:91`, which returns an adapter exposing
`is_real_data` at `:119`) wrapping precisely this file, and being called by the
service's own router at `routers/planning.py:76`. Within one service, the
scenario engine reads BTS through the adapter and the training pipeline reads
the identical CSV with `csv.DictReader`.

**Fix.** Route both builders through the adapter, and assert `is_real_data` before
training. This is the smallest change that makes the L2→L3 path genuinely
contract-governed rather than merely claimable.

**Verify.** Assert the training path raises if `is_real_data` is false.

### 4.7 P2 — the delay model's score is specified but unwired

`ROADMAP4.md:978` states the delay score is to be "used by the planning engine to
weight delay costs in scenario projections." The engine never calls the model
(§4 preamble). The model is trained, served and unused.

**Fix.** Either wire `DelayModel.predict` into the scenario engine's cost
weighting, or record the capability as not-yet-implemented in
`docs/services/planning-service/SPEC.md`.

### 4.8 P1 — reporting gate

Until §4.1 through §4.6 are resolved, the following are leakage-inflated and
must not be quoted, exported to a dashboard, or asserted in any test:

- delay classifier `auc` (`delay_model.py:94`) — measures recovery of a rule
- demand regressor `mae` and `rmse` (`demand_model.py:136-140`) — target is
  duplicated into a feature
- any statement about the predictive quality of either model

The queue forecaster's MAE (`ml/training.py:133`) is **not** affected by these
defects: its target, observed queue depth, is not present in its 12 features.

---

## 5. Fix order

Sequenced so that nothing is measured mid-repair, and so the cheapest structural
fix lands before the most expensive.

1. **Add the OTP ingest.** New `scripts/helper_filter_bts_otp.py` mirroring
   `filter_and_remap` (`helper_filter_bts_data.py:92`) with the same CLI shape
   (`--reference-airport`, `--kart-iata`, `--output`), writing
   `data/bts/OTP_reference.csv`. Unblocks §4.1.
2. **Rebuild the delay labels** on observed `ARR_DELAY15` / `DEP_DELAY15` (§4.1).
3. **Remove leakage.** Delete `historical_otp` (§4.2); repoint
   `historical_avg_pax` to the previous month (§4.3).
4. **Remove constant features** and reconcile training with inference (§4.4,
   §4.5). Drop `day_of_week` outright — monthly T-100 cannot supply it.
5. **Route training through the adapter** and assert `is_real_data` (§4.6).
6. **Re-measure.** Only now are MAE, RMSE and AUC meaningful (§4.8). Add
   `scripts/` and test coverage for the assertions in §6.
7. **Decide the delay score's fate** — wire or record as unimplemented (§4.7).

Steps 1-2 are the only ones requiring new external data. Steps 3-5 are contained
edits to one file plus the two feature lists.

---

## 6. Verification checklist

Assertions to add, each cheap and each currently failing:

```python
# §4.1 delay labels are observed, not derived
assert set(df["label_source"].unique()) == {"otp"}

# §4.2 / §4.3 no target or transform of it appears as a feature
for col in FEATURE_COLS:
    assert not df[col].equals(df["was_delayed"])
assert not df["historical_avg_pax"].equals(df["actual_pax"])

# §4.3 the prior-value feature actually leads the target
assert (df.groupby(["origin", "destination"])["month"]
          .diff().fillna(1) >= 1).all()

# §4.4 features vary
low_cardinality = df[FEATURE_COLS].nunique()
assert (low_cardinality > 1).all(), low_cardinality[low_cardinality == 1].index

# §4.5 one shared feature builder for training and inference
assert build_features(train_row) == build_features(serve_row)

# §4.6 the L2 path is contract-governed
assert adapter.is_real_data
```

Additional checks worth adding alongside the above:

- `docs/services/analysis-service/SPEC.md` exists and covers the anomaly
  detector, the 14 `ActionType`s, the approval classes, the command topics and
  their producers (§2.1).
- `ROUTES.md` has a section for `cost-service` and `planning-service` (§2.2).
- A producer exists for `passengers.commands` and `baggage.commands`, or
  `EVENT_BUS.md:33-34` is corrected to record them as unproduced (§3.4).
- `docs/dashboards/ML.md` lists the planning-service models (§3.7).
- Either `models/rl_policy.zip` ships, or the RL capability is documented as
  untrained (§3.6).

---

## 7. Summary

| # | Finding | Severity |
| - | ------- | -------- |
| 4.1 | Delay labels derived from a load-factor threshold, not observations | P1 |
| 4.2 | Delay target leaks into `historical_otp` | P1 |
| 4.3 | Demand target duplicated into `historical_avg_pax` | P1 |
| 4.4 | 4 of 8 delay and 4 of 7 demand features are constants | P1 |
| 4.8 | Reported MAE, RMSE, AUC are leakage-inflated | P1 |
| 2.1 | `analysis-service` has neither `SPEC.md` nor `SKILL.md` | P2 |
| 2.2 | `cost-service` and `planning-service` absent from `ROUTES.md` | P2 |
| 3.4 | 2 of 3 command topics have no producer | P2 |
| 3.5 | 3 of 14 action types can become commands | P2 |
| 3.2 | Two parallel adapter mechanisms, not one contract | P2 |
| 4.5 | Train/serve skew on 3 features | P2 |
| 4.6 | Training reads the reference CSV directly, bypassing the adapter | P2 |
| 4.7 | Delay score specified but never called by the engine | P2 |
| 3.6 | RL policy artefact not shipped | P3 |
| 3.7 | `docs/dashboards/ML.md` omits the planning models | P3 |

The five P1 items share one root cause: the training builders were written to
populate the feature vectors the models expected, and where a value was
unavailable a constant or a proxy was substituted without recording that the
result was no longer a measurement. The fix is to source the values properly
rather than to keep the placeholders.

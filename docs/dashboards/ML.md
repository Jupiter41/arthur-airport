# Machine Learning & AI — Arthur International Airport Digital Twin

This document describes all ML/AI features integrated into the airport digital twin,
how they interact, and how to use them. There are four distinct ML/AI subsystems plus
a rule-based prescriptive layer that bridges them.

---

## Architecture overview

```
┌───────────────────────────────────────────────────────────────────────┐
│                         ML/AI Pipeline                                │
│                                                                       │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐  │
│  │ passenger-   │     │ analysis-    │     │ analysis-service     │  │
│  │ service      │     │ service      │     │ (NLP)                │  │
│  │              │     │              │     │                      │  │
│  │ LightGBM     │────▶│ Bottleneck   │────▶│ Natural Language     │  │
│  │ Queue        │     │ Detection &  │     │ Query Interface      │  │
│  │ Forecasting  │     │ Recommender  │     │ (LLM + templates)    │  │
│  └──────────────┘     └──────┬───────┘     └──────────────────────┘  │
│                              │                                        │
│                    ┌─────────┴─────────┐                             │
│                    │                   │                              │
│              ┌─────▼──────┐    ┌───────▼──────┐                      │
│              │ RL Agent   │    │ Anomaly      │                      │
│              │ (PPO)      │    │ Detection    │                      │
│              │            │    │ (Isolation   │                      │
│              │ Autonomous │    │  Forest)     │                      │
│              │ Operations │    │              │                      │
│              └────────────┘    └──────────────┘                      │
└───────────────────────────────────────────────────────────────────────┘
```

**Data flow:** Every ML component consumes the simulation state via Kafka events
(`sim.clock`, `flights.events`, `passengers.events`, `baggage.events`, `weather.events`,
`incidents.events`). No ML component makes direct HTTP calls to other services.

---

## 1. LightGBM — Security queue forecasting

**Service:** `passenger-service` (port 8002)  
**Model:** LGBMRegressor (gradient boosted decision tree)  
**Purpose:** Predict security checkpoint queue depth up to 90 sim-minutes ahead,
per terminal (A, B, C).

### How it works

1. **Feature collection** — Every sim-minute tick, the passenger-service extracts
   a 12-feature vector per terminal:

   | Feature                   | Description                                       |
   | ------------------------- | ------------------------------------------------- |
   | `hour_of_day`             | 0–23, from sim clock                              |
   | `day_of_week`             | 0–6 (Mon–Sun)                                     |
   | `month`                   | 1–12                                              |
   | `season`                  | Ordinal (spring=0 … winter=3)                     |
   | `weather_category`        | Ordinal: CAVOK=0, VMC=1, IMC=2, LIFR=3            |
   | `flights_departing_90min` | Scheduled departures in next 90 sim-min           |
   | `expected_pax_90min`      | Expected passenger volume from scheduled flights  |
   | `load_factor`             | Average load factor for upcoming flights          |
   | `incident_in_terminal`    | Binary — active incident in this terminal         |
   | `adjacent_congestion`     | Binary — adjacent terminal queue > threshold      |
   | `special_event`           | Binary — special event flag active                |
   | `event_pax_multiplier`    | Multiplier for current special event (1.0 = none) |

2. **Training row collection** — Each tick, the actual queue depth is paired with
   the feature vector and buffered in a deque. Buffers are flushed hourly to Parquet
   files for persistence.

3. **Periodic retraining** — Every 3 sim-days, the model retrains from the accumulated
   Parquet data if at least 500 rows are available. After retraining, models are saved
   to `/app/models/forecast_{A,B,C}.lgbm` and hot-reloaded without restart.

4. **Inference** — The trained model predicts queue depth at horizons of 15, 30, 60,
   and 90 sim-minutes. If no trained model exists yet, a fallback linear formula is
   used: `forecast = expected_pax_next_90min × 0.35`.

5. **Congestion detection** — If the forecast predicts wait time exceeding a threshold
   for N consecutive ticks, a `SecurityCongestionDetected` Kafka event is emitted,
   which triggers bottleneck detection in the analysis-service.

### Model hyperparameters

```python
LGBMRegressor(
    n_estimators=200,
    learning_rate=0.05,
    max_depth=6,
    num_leaves=31,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_samples=20,
    verbosity=-1,
)
```

### API endpoints

| Endpoint                          | Method | Description                                                    |
| --------------------------------- | ------ | -------------------------------------------------------------- |
| `/passengers/forecast`            | GET    | Returns per-terminal queue depth forecast at multiple horizons |
| `/passengers/forecast/importance` | GET    | Returns LightGBM feature importance scores                     |
| `/passengers/forecast/congestion` | GET    | Returns current congestion risk assessment                     |

### Key files

| File                                          | Purpose                                                 |
| --------------------------------------------- | ------------------------------------------------------- |
| `services/passenger-service/ml/features.py`   | Feature engineering (12-feature vector)                 |
| `services/passenger-service/ml/training.py`   | LGBMRegressor training, serialisation, retraining logic |
| `services/passenger-service/ml/inference.py`  | Model loading, prediction, fallback                     |
| `services/passenger-service/ml/congestion.py` | Congestion detection from forecast output               |

---

## 2. Reinforcement learning — Autonomous operations

**Service:** `analysis-service` (port 8007)  
**Algorithm:** PPO (Proximal Policy Optimisation) via `stable-baselines3`  
**Purpose:** Learn an optimal policy for operational interventions (open lanes,
reassign gates, hold flights, etc.) that minimises delay minutes and missed connections.

### How it works

1. **Environment** — A Gymnasium-compatible environment (`AirportOpsEnv`) wraps the
   analysis-service's operational state and what-if engine. The state space is a
   22-dimensional continuous vector:
   - Security queue depths and forecast waits (6 dims, 3 terminals × 2)
   - Free gate count per terminal (3 dims)
   - Flight metrics: delay total, scheduled/boarding/departed/approaching/holding/landed counts (7 dims)
   - Vehicle utilisation, weather category, incident count, bottleneck count (4 dims)
   - Runway capacity percentage (1 dim)
   - Simulation hour (1 dim)

2. **Action space** — 7 discrete actions:

   | Action                   | Effect                                                   |
   | ------------------------ | -------------------------------------------------------- |
   | `no_action`              | Do nothing                                               |
   | `open_security_lane`     | Open an additional security lane in the busiest terminal |
   | `reassign_gate`          | Reassign a flight to a better gate                       |
   | `hold_connecting_flight` | Hold a departure for connecting passengers               |
   | `fast_track_passengers`  | Fast-track a group through security                      |
   | `redirect_baggage`       | Reroute baggage to less-loaded carousel                  |
   | `redistribute_vehicles`  | Rebalance ground vehicles between terminals              |

3. **Reward function** — Shaped reward combining:
   - `-0.01` per delay-minute delta
   - `-10.0` per missed connection
   - `-5.0` per active bottleneck
   - `+10.0` per resolved bottleneck

4. **Training** — Offline training runs the simulation in BULK mode (3600×) to
   generate episodes quickly. Each episode lasts 120 sim-minutes. The trained model
   is saved to `/app/models/rl_policy.zip`.

5. **Deployment** — The RL agent is one of the autonomous mode options in the
   settings UI. When `autonomous_mode` is set to `rl`, the agent selects an action
   every tick based on the current state observation.

### Training

```bash
# Inside the analysis-service container or locally with dependencies
python -m training.train_rl --episodes 1000 --output /app/models/rl_policy.zip

# Benchmark against rule-based and no-intervention baselines
python -m training.benchmark_rl --model /app/models/rl_policy.zip --episodes 100
```

### Configuration

| Env var         | Default                     | Description               |
| --------------- | --------------------------- | ------------------------- |
| `RL_MODEL_PATH` | `/app/models/rl_policy.zip` | Path to trained PPO model |

### Key files

| File                                                 | Purpose                                    |
| ---------------------------------------------------- | ------------------------------------------ |
| `services/analysis-service/services/rl/env.py`       | Gymnasium environment definition           |
| `services/analysis-service/services/rl/agent.py`     | Model loading, inference, action selection |
| `services/analysis-service/training/train_rl.py`     | PPO training script                        |
| `services/analysis-service/training/benchmark_rl.py` | Baseline comparison benchmark              |

---

## 3. Anomaly detection — Isolation Forest

**Service:** `analysis-service` (port 8007)  
**Algorithm:** IsolationForest (scikit-learn)  
**Purpose:** Detect operational anomalies by identifying deviations from normal
simulation behaviour across 14 metric dimensions.

### How it works

1. **Feature collection** — Every tick, a 14-dimensional feature vector is extracted:

   | Feature                   | Description                            |
   | ------------------------- | -------------------------------------- |
   | `security_queue_{A,B,C}`  | Queue depths per terminal              |
   | `security_wait_{A,B,C}`   | Wait times per terminal                |
   | `baggage_util_avg`        | Average baggage conveyor utilisation   |
   | `delay_minutes_total`     | Total accumulated delay minutes        |
   | `delayed_flight_count`    | Number of delayed flights              |
   | `active_incident_count`   | Active incident count                  |
   | `vehicle_util_avg`        | Average ground vehicle utilisation     |
   | `runway_capacity_pct`     | Current runway capacity as % of normal |
   | `weather_category`        | Ordinal weather category               |
   | `active_bottleneck_count` | Active bottleneck count                |

2. **Rolling buffer** — Up to 2,000 feature vectors stored (≈33 sim-hours).

3. **Training** — IsolationForest is retrained every 60 sim-minutes once the buffer
   reaches 120 samples (2 hours warm-up).

4. **Scoring** — Each tick, the current observation is scored:
   - `normal` — decision function ≥ -0.1
   - `amber` — decision function between -0.3 and -0.1
   - `red` — decision function < -0.3

5. **Root cause** — Per-feature z-scores identify which metric is deviating most.
   Recent Kafka events near the anomaly timestamp are scanned to trace the triggering
   event chain.

### Model parameters

```python
IsolationForest(
    n_estimators=100,
    contamination=0.05,
    random_state=42,
    n_jobs=1,
)
```

### API endpoints

| Endpoint              | Method | Description                                              |
| --------------------- | ------ | -------------------------------------------------------- |
| `/analysis/anomalies` | GET    | Returns current anomaly status, z-scores, and root cause |

### Key files

| File                                            | Purpose                                                  |
| ----------------------------------------------- | -------------------------------------------------------- |
| `services/analysis-service/services/anomaly.py` | AnomalyDetector class with training, scoring, root cause |

---

## 4. Natural language interface — LLM + template fallback

**Service:** `analysis-service` (port 8007)  
**Backend:** Any OpenAI-compatible API (configurable) or template-based fallback  
**Purpose:** Allow operators to query the simulation state in plain English, inject
incidents via natural language, receive narrated commentary, and generate post-scenario
reports.

### Features

| Feature                   | API endpoint               | Description                                                                                          |
| ------------------------- | -------------------------- | ---------------------------------------------------------------------------------------------------- |
| **NL Query**              | `POST /analysis/query`     | Ask questions like "How many flights are delayed?" or "What's causing the bottleneck in Terminal B?" |
| **NL Incident Injection** | `POST /analysis/inject-nl` | "Inject a severe security breach in Terminal B at gate B07" → parsed into structured inject request  |
| **Narration Mode**        | `GET /analysis/narration`  | Real-time running commentary of significant events in the simulation                                 |
| **After-Action Report**   | `POST /analysis/report`    | Generates a narrative summary at the end of a scenario run                                           |

### Architecture

```
User → POST /analysis/query → { question: "What's causing delays?" }
                                       │
                              ┌────────▼────────┐
                              │ LLM available?   │
                              └────────┬────────┘
                            yes │          │ no
                     ┌──────────▼┐   ┌─────▼──────────┐
                     │ OpenAI API │   │ Template engine │
                     │ + context  │   │ (regex + rules) │
                     └──────────┬┘   └─────┬──────────┘
                                └──────┬───┘
                                       ▼
                              { answer: "...", source: "llm"|"template" }
```

The system **always works without an LLM API key**. Template responses use regex
pattern matching against common question types and structured state data to produce
useful answers. When an LLM endpoint is configured, the full airport state context
is sent as system prompt context for richer answers.

### Configuration

| Env var        | Default       | Description                                    |
| -------------- | ------------- | ---------------------------------------------- |
| `LLM_BASE_URL` | (none)        | Base URL for OpenAI-compatible completions API |
| `LLM_API_KEY`  | (none)        | API key (omit for template-only mode)          |
| `LLM_MODEL`    | `gpt-4o-mini` | Model name to request                          |

### Using with a local LLM

The NLP interface works with any OpenAI-compatible endpoint. To use a local model:

```bash
# Example with Ollama (running on host machine)
export LLM_BASE_URL=http://host.docker.internal:11434/v1
export LLM_API_KEY=ollama  # any non-empty string
export LLM_MODEL=llama3.1

# Then start the stack
docker compose up --build
```

### Key files

| File                                                  | Purpose                                     |
| ----------------------------------------------------- | ------------------------------------------- |
| `services/analysis-service/services/nlp/query.py`     | NL query engine with LLM and template modes |
| `services/analysis-service/services/nlp/llm.py`       | LLM adapter (OpenAI-compatible HTTP client) |
| `services/analysis-service/services/nlp/inject.py`    | NL incident injection parser                |
| `services/analysis-service/services/nlp/narration.py` | Real-time narration generator               |
| `services/analysis-service/services/nlp/report.py`    | After-action report generator               |

---

## 5. Prescriptive layer — Bottleneck detection, recommendations & what-if

While not machine learning per se, the prescriptive layer is the **intelligence bridge**
connecting ML outputs to operational actions.

### Bottleneck detection

Rule-based detectors monitor 6 domains every tick:

| Domain              | Trigger condition                                                    |
| ------------------- | -------------------------------------------------------------------- |
| Security queue      | Forecast wait > 20 min with confidence > 0.75 (uses LightGBM output) |
| Gate utilisation    | < 2 free gates in a terminal with queued flights                     |
| Baggage throughput  | Make-up carousel utilisation > 90% for 5+ sim-minutes                |
| Connection clusters | 5+ connecting passengers on same delayed inbound + same outbound     |
| Ground vehicles     | Vehicle type utilisation > 85% with upcoming demand                  |
| Runway capacity     | Weather-reduced capacity below 60% of normal                         |

### Recommendation engine

For each active bottleneck, template-based heuristics generate ranked interventions:

- Security → open lanes, early gate calls, redirect check-in
- Gates → alternate gate, delay taxi, swap departures
- Connections → hold flight, fast-track, rebook
- Weather → ground delay program with flight-level delay assignment

### What-if analysis

`POST /analysis/what-if` forks the simulation into an in-memory shadow, applies a
proposed action, runs forward N sim-minutes, and returns projected KPIs. Supports
comparing up to 3 actions simultaneously.

### Autonomous mode

The settings UI offers four autonomous operation modes:

| Mode        | Description                                                                      |
| ----------- | -------------------------------------------------------------------------------- |
| `off`       | Manual operation only                                                            |
| `rule`      | Rule-based: applies top recommendation automatically when confidence > threshold |
| `rl`        | RL agent: PPO model selects actions based on state observation                   |
| `threshold` | Conservative: only applies high-confidence recommendations with safety guards    |

Safety guards: autonomous mode **never** auto-applies flight cancellation, runway closure,
or terminal evacuation — those always require human confirmation.

### API endpoints

| Endpoint                      | Method | Description                                         |
| ----------------------------- | ------ | --------------------------------------------------- |
| `/analysis/bottlenecks`       | GET    | All active bottlenecks with severity and root cause |
| `/analysis/recommendations`   | GET    | Top 3 ranked recommendations                        |
| `/analysis/what-if`           | POST   | Shadow simulation with projected KPIs               |
| `/analysis/anomalies`         | GET    | Current anomaly status                              |
| `/analysis/autonomous/status` | GET    | Autonomous mode status and action log               |

### Key files

| File                                                | Purpose                                         |
| --------------------------------------------------- | ----------------------------------------------- |
| `services/analysis-service/services/detectors.py`   | Bottleneck detection rules                      |
| `services/analysis-service/services/recommender.py` | Recommendation generation and ranking           |
| `services/analysis-service/services/whatif.py`      | What-if shadow simulation engine                |
| `services/analysis-service/services/state.py`       | Operational state aggregation from Kafka events |

---

## How they work together

```
Simulation tick (sim.clock)
     │
     ├─▶ passenger-service
     │       │
     │       ├─ Collect features → train LightGBM (every 3 days)
     │       ├─ Predict queue depth at 15/30/60/90 min horizons
     │       └─ Emit SecurityCongestionDetected if threshold exceeded
     │
     ├─▶ analysis-service (Kafka consumer)
     │       │
     │       ├─ Update OperationalState from all domain events
     │       ├─ Run 6 bottleneck detectors (security uses LightGBM forecast)
     │       ├─ Generate recommendations for active bottlenecks
     │       ├─ Score anomaly detector (IsolationForest)
     │       │
     │       └─ If autonomous_mode != "off":
     │            ├─ mode="rl" → PPO agent selects action from state
     │            ├─ mode="rule" → apply top recommendation if confidence > threshold
     │            └─ mode="threshold" → conservative rule application
     │
     └─▶ NLP (on-demand via API)
              ├─ POST /analysis/query → answer questions about current state
              ├─ POST /analysis/inject-nl → parse NL into structured incident
              ├─ GET /analysis/narration → real-time commentary
              └─ POST /analysis/report → scenario after-action report
```

---

## Quick start

```bash
# 1. Start the full stack (LightGBM and anomaly detection work out of the box)
docker compose up --build

# 2. Wait for LightGBM to collect enough data (~2 sim-hours at 60x speed)
#    Then check forecast endpoint:
curl http://localhost:8002/passengers/forecast | python3 -m json.tool

# 3. Check anomaly detection (needs ~2 sim-hours warm-up):
curl http://localhost:8007/analysis/anomalies | python3 -m json.tool

# 4. Check bottlenecks and recommendations:
curl http://localhost:8007/analysis/bottlenecks | python3 -m json.tool
curl http://localhost:8007/analysis/recommendations | python3 -m json.tool

# 5. Ask the NLP engine (works without LLM, uses templates):
curl -X POST http://localhost:8007/analysis/query \
  -H "Content-Type: application/json" \
  -d '{"question": "How many flights are delayed?"}'

# 6. (Optional) Enable LLM-powered NLP:
export LLM_BASE_URL=https://api.openai.com/v1
export LLM_API_KEY=sk-...
docker compose up --build analysis-service

# 7. (Optional) Train RL agent:
docker compose exec analysis-service python -m training.train_rl \
  --episodes 1000 --output /app/models/rl_policy.zip

# 8. Enable autonomous mode via settings UI or API:
curl -X POST http://localhost:8006/sim/settings \
  -H "Content-Type: application/json" \
  -d '{"autonomous_mode": "rl"}'
```

---

## Dependencies

| Component         | Library             | Version | Service           |
| ----------------- | ------------------- | ------- | ----------------- |
| Queue forecasting | `lightgbm`          | ≥4.3.0  | passenger-service |
| RL environment    | `gymnasium`         | ≥1.0.0  | analysis-service  |
| RL training       | `stable-baselines3` | ≥2.3.0  | analysis-service  |
| Anomaly detection | `scikit-learn`      | ≥1.4.0  | analysis-service  |
| LLM adapter       | `httpx`             | ≥0.27.0 | analysis-service  |
| Numerical         | `numpy`             | ≥1.26.0 | both              |

# Phase 5 — Advanced ML & AI — Implementation Plan

**Date:** 2026-04-10
**Scope:** P5-1-1 through P5-3-3 (RL operations, NL interface, anomaly detection)

---

## Architecture Overview

All Phase 5 features are added **within the existing analysis-service** (port 8007).
No new microservice is needed — the analysis-service already aggregates operational
state from Kafka events and exposes REST + WebSocket APIs. We extend it with:

1. **RL module** — `services/rl/` — Gymnasium environment + PPO agent
2. **NLP module** — `services/nlp/` — LLM-backed query, injection, narration
3. **Anomaly module** — `services/anomaly.py` — Isolation forest

A new separate **training script** lives in `services/analysis-service/training/`
for offline RL training (runs via `docker compose run` or locally).

---

## Phase 5.3 — Anomaly Detection (implement first — lowest risk)

### P5-3-1 — Isolation forest baseline model

**Approach:**

- Collect per-minute metric vectors from the in-memory OperationalState on each tick:
  - Per-terminal security queue depth (3 values)
  - Per-terminal security forecast wait (3 values)
  - Baggage zone utilisation (avg across active zones)
  - Total delay minutes (sum across active flights)
  - Active incident count
  - Ground vehicle utilisation (avg)
  - Runway capacity %
  - Weather category (ordinal: CAVOK=0, VMC=1, IMC=2, LIFR=3)
- Total feature vector: ~14 floats
- Use a rolling buffer (`collections.deque`, maxlen=2000 minutes = ~33h)
- Every 60 sim-minutes, retrain an `IsolationForest` from scikit-learn on the
  buffer if buffer has ≥ 120 samples
- On each tick after first training, score the current observation
- Expose z-score-like anomaly score (decision_function → normalized) at
  `GET /analysis/anomalies`

**Files to create/edit:**

- `services/analysis-service/services/anomaly.py` (new)
- `services/analysis-service/routers/analysis.py` (add endpoint)
- `services/analysis-service/kafka/consumer.py` (collect metrics + call anomaly on tick)
- `services/analysis-service/requirements.txt` (add scikit-learn, numpy)

### P5-3-2 — Anomaly Prometheus metrics + Grafana

**Approach:**

- Export `analysis_anomaly_score` gauge per-service (single service for now)
- Export `analysis_anomaly_status` gauge (0=normal, 1=amber, 2=red) based on thresholds:
  - score < -0.3 → red (severe anomaly)
  - score < -0.1 → amber (mild anomaly)
  - else → green (normal)
- Add alert rule in `infra/prometheus/alerts.yml`
- Add Grafana panel in `infra/grafana/`

**Files to create/edit:**

- `services/analysis-service/metrics.py` (add gauges)
- `infra/prometheus/alerts.yml` (add anomaly alert)
- `infra/grafana/dashboards/anomaly.json` (new panel, optional)

### P5-3-3 — Root cause trace

**Approach:**

- When anomaly is detected (score < threshold), walk backward through the
  recent Kafka events cached in the consumer's event buffer (last 30 minutes)
- Identify the first event whose timestamp correlates with the anomaly onset
- Use simple heuristic: find the event type that had the biggest metric deviation
  from mean at the time the anomaly score first crossed threshold
- Return as `root_cause` field in the anomaly response

**Files to edit:**

- `services/analysis-service/services/anomaly.py` (add root_cause logic)

---

## Phase 5.1 — Reinforcement Learning

### P5-1-1 — RL environment definition

**State space** (continuous, Box):

- Security queue depth × 3 terminals
- Security forecast wait × 3 terminals
- Free gates per terminal × 3
- Total delay minutes
- Flight count by status (scheduled, boarding, departed, approaching, holding, landed) × 6
- Ground vehicle utilisation (avg)
- Weather category (ordinal 0-3)
- Active incident count
- Active bottleneck count
- Runway capacity %

Total: ~22 continuous dimensions

**Action space** (Discrete, 7 actions): 0. No action (observe)

1. Open security lane (least-free terminal)
2. Reassign gate (neediest flight)
3. Hold connecting flight (largest cluster)
4. Fast-track passengers (at-risk cluster)
5. Redirect baggage (overloaded zone)
6. Redistribute vehicles (overloaded type)

**Reward function:**

- Negative total delay minutes delta (minimize delay)
- Negative missed connections (each = -10)
- Negative active bottleneck count × -5
- Positive for resolved bottleneck × +10

### P5-1-2 — Gymnasium environment wrapper

**Approach:**

- Create `services/analysis-service/services/rl/env.py`
- Wraps a lightweight simulation step:
  - Uses the what-if engine's shadow state to project N minutes forward
  - Each `step()` applies one action, advances shadow by 1 sim-minute
  - Returns new state vector, reward, terminated/truncated flags
- Episode = 120 sim-minutes (one window)
- Reset creates fresh shadow from current OperationalState

### P5-1-3 — PPO training

**Approach:**

- Create `services/analysis-service/training/train_rl.py`
- Uses stable-baselines3 PPO with MlpPolicy
- Can run standalone: `python training/train_rl.py`
- Trains on simulated episodes at BULK speed
- Saves model to `services/analysis-service/models/rl_policy.zip`
- Also supports loading from environment variable path

### P5-1-4 — Comparison benchmark

**Approach:**

- Create `services/analysis-service/training/benchmark_rl.py`
- Runs N episodes with: (a) no intervention, (b) rule-based, (c) RL agent
- Outputs CSV comparison report

### P5-1-5 — Deploy in autonomous mode

**Approach:**

- Add `rl_agent` as a fourth autonomous mode option in AutonomousSettings
- When mode = "rl_agent", load the trained PPO policy and use it to select
  actions instead of the rule-based recommender
- Add mode enum: `off`, `rule_based`, `threshold`, `rl_agent`

---

## Phase 5.2 — Natural Language Operations Interface

### LLM Strategy

Use an **OpenAI-compatible API adapter** supporting:

1. OpenAI API (user provides `OPENAI_API_KEY`)
2. Any OpenAI-compatible endpoint (Groq, Together, local Ollama, etc.)
   via `LLM_BASE_URL` + `LLM_API_KEY` + `LLM_MODEL`
3. **Template-based fallback** when no LLM is configured — uses structured
   string templates for queries and reports (no external API needed)

Environment variables:

```
LLM_BASE_URL=https://api.openai.com/v1    # or https://api.groq.com/openai/v1
LLM_API_KEY=sk-...                          # or gsk-...
LLM_MODEL=gpt-4o-mini                       # or llama-3.3-70b-versatile
```

### P5-2-1 — Natural language query endpoint

**Approach:**

- Add `POST /analysis/query` accepting `{ "question": "..." }`
- Build a context string from current OperationalState snapshot:
  - Flight summary (counts by status, top delays)
  - Security queue depths
  - Active incidents
  - Active bottlenecks
  - Weather conditions
  - Recent recommendations
- Send to LLM with system prompt: "You are an airport operations analyst..."
- Parse structured response
- Template fallback: pattern-match common questions and return formatted state data

### P5-2-2 — Natural language incident injection

**Approach:**

- Add `POST /analysis/nl-inject` accepting `{ "command": "..." }`
- Use LLM to extract: incident type, severity, location from natural language
- Map to structured `POST /incidents/inject` payload
- Validate extracted parameters before sending
- Template fallback: regex-based intent extraction for known patterns

### P5-2-3 — Simulation narration mode

**Approach:**

- Add `narration_enabled` toggle in settings
- On significant events (flight delay, incident, bottleneck, weather change),
  accumulate event summaries in a buffer
- Every 5 sim-minutes (configurable), send batch to LLM for narrative generation
- Emit narration via WebSocket `analysis.events` with type `NarrationGenerated`
- Template fallback: structured event-to-sentence templates

### P5-2-4 — After-action report generator

**Approach:**

- Add `POST /analysis/report` endpoint
- Collects: scenario results, bottleneck history, recommendation history,
  autonomous action log, what-if log
- Sends structured summary to LLM for prose generation
- Returns markdown document
- Template fallback: structured report with tables and bullet points

---

## Implementation Order

1. **5.3 Anomaly detection** (P5-3-1 → P5-3-2 → P5-3-3) — ~2h
   - Standalone, no external deps beyond scikit-learn
   - Adds value immediately (new endpoint + Grafana)

2. **5.1 RL environment** (P5-1-1 → P5-1-2 → P5-1-3 → P5-1-4 → P5-1-5) — ~4h
   - Depends on stable analysis-service state module
   - gym + stable-baselines3 are well-tested libraries

3. **5.2 NL interface** (P5-2-1 → P5-2-2 → P5-2-3 → P5-2-4) — ~3h
   - LLM adapter pattern with fallback
   - Dashboard integration for narration + query panel

4. **Dashboard + Gateway wiring** — ~1h
5. **Tests + CI** — ~1h

---

## Docker Changes

- analysis-service Dockerfile: add libgomp1 for LightGBM (if needed)
- requirements.txt additions:
  - `scikit-learn>=1.4.0`
  - `numpy>=1.26.0`
  - `gymnasium>=1.0.0`
  - `stable-baselines3>=2.3.0`
  - `httpx>=0.27.0` (for LLM API calls)
- docker-compose.yml: add `LLM_*` env vars to analysis-service

---

## Risk Mitigation

- **LLM unavailable**: All NL features have template-based fallbacks. System works
  without any API key — just less eloquent.
- **RL training slow**: Training runs offline, not in the hot path. Pre-trained model
  shipped as default. Fallback to rule-based if model missing.
- **Anomaly false positives**: Conservative thresholds + minimum buffer size before
  first training. Model updates every 60 sim-minutes for adaptation.

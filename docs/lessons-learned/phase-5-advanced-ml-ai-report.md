# Phase 5 — Advanced ML & AI: Implementation Report

**Date:** 2025-07-08
**Tasks:** P5-1-1 → P5-1-5 (RL), P5-2-1 → P5-2-4 (NLP), P5-3-1 → P5-3-3 (Anomaly)

---

## What was done

### 5.1 — Reinforcement Learning for Operations Optimisation

| File                                                 | Purpose                                                                                                                     |
| ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `services/analysis-service/services/rl/env.py`       | Gymnasium environment: 22-dim state, 7 discrete actions, reward = −delay_delta − 10×missed_connections ± bottleneck bonuses |
| `services/analysis-service/services/rl/agent.py`     | PPO policy loader with lazy init, confidence estimation from action probabilities                                           |
| `services/analysis-service/training/train_rl.py`     | stable-baselines3 PPO training script (MlpPolicy, 4 parallel envs, eval callback)                                           |
| `services/analysis-service/training/benchmark_rl.py` | Comparison benchmark: no_intervention vs rule_based vs rl_agent, CSV output                                                 |
| `services/analysis-service/services/autonomous.py`   | Added `evaluate_rl_agent()` bridging RL predictions to `ActionApplied` log entries                                          |
| `services/analysis-service/kafka/consumer.py`        | RL mode dispatch: `auto_settings.mode == "rl_agent"` routes to RL agent instead of rule engine                              |
| `services/analysis-service/models/domain.py`         | `AutonomousMode` enum: off / rule_based / threshold / rl_agent                                                              |

**State space (22 dims):** gate utilisation, runway utilisation, security queue depth, immigration queue depth, active incidents count, weather category (ordinal), conveyor throughput, avg departure delay, avg arrival delay, missed connections, pax in terminal, bags in system, holding stack size, taxiway congestion, check-in queue depth, boarding queue depth, hour-of-day (sin/cos), day-of-week (sin/cos), total flights, delayed ratio, diverted count, cancelled count.

**Action space (7):** noop, open_security_lane, close_security_lane, reassign_gate, hold_departures, issue_gdp, surge_baggage_staff.

### 5.2 — Natural Language Operations Interface

| File                                                  | Purpose                                                                                                                           |
| ----------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `services/analysis-service/services/nlp/llm.py`       | OpenAI-compatible adapter (works with OpenAI, Groq, Ollama, any compatible API). Falls back gracefully when no LLM is configured. |
| `services/analysis-service/services/nlp/query.py`     | NL query engine: LLM with airport state context + template fallback (12 intent categories matched via keyword regex)              |
| `services/analysis-service/services/nlp/inject.py`    | NL incident injection parser: LLM JSON extraction + regex fallback for type/severity/location                                     |
| `services/analysis-service/services/nlp/narration.py` | Live narration engine: buffers significant events, generates commentary every N ticks via LLM or templates                        |
| `services/analysis-service/services/nlp/report.py`    | After-action report: 5-section Markdown report (overview, timeline, interventions, impact, recommendations)                       |

**LLM configuration:** Set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` env vars in docker-compose.yml. Works with:

- OpenAI: `https://api.openai.com/v1` + `gpt-4o-mini`
- Groq: `https://api.groq.com/openai/v1` + `llama-3.1-70b-versatile`
- Ollama: `http://host.docker.internal:11434/v1` + `llama3.1`
- No API key: all NLP features degrade to template-based responses (no LLM calls)

**Endpoints added:**

- `POST /analysis/query` — NL query
- `POST /analysis/nl-inject` — NL incident injection
- `GET /analysis/narration` — Latest narration entries
- `PATCH /analysis/narration` — Enable/disable narration, adjust interval
- `POST /analysis/report` — Generate after-action report
- `GET /analysis/llm-config` — Show current LLM configuration status

### 5.3 — Anomaly Detection

| File                                            | Purpose                                                                                                                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `services/analysis-service/services/anomaly.py` | IsolationForest detector: 14-feature extraction, rolling 2000-sample buffer, retrains every 60 ticks, z-score per feature, root cause tracing via recent Kafka event log |

**Features (14):** gate_util, runway_util, security_queue, immigration_queue, active_incidents, weather_cat, conveyor_throughput, avg_dep_delay, avg_arr_delay, missed_connections, pax_in_terminal, bags_in_system, holding_stack, taxiway_congestion.

**Thresholds:** Amber at score < −0.1, Red at score < −0.3. Minimum 120 samples before training.

**Prometheus metrics:** `analysis_anomaly_score`, `analysis_anomaly_status`, `analysis_anomaly_feature_zscore{feature=...}` — ready for Grafana alerting rules.

### Dashboard Integration

| File                                                                         | Purpose                                                                                       |
| ---------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| `dashboards/art-dashboard/src/pages/IncidentConsole/Phase5Panels.tsx`        | 5 React components: NLQueryPanel, NLInjectPanel, AnomalyPanel, NarrationFeed, ReportGenerator |
| `dashboards/art-dashboard/src/pages/IncidentConsole/IncidentConsolePage.tsx` | Integrated Phase 5 panels into the incident console layout                                    |
| `dashboards/art-dashboard/src/hooks/useApi.ts`                               | Added 7 API methods for Phase 5 endpoints                                                     |
| `dashboards/art-dashboard/src/pages/Settings/SettingsPage.tsx`               | Autonomous mode selector: dropdown with off / rule_based / threshold / rl_agent options       |

---

## Design decisions

1. **Template fallback for all NLP features.** Every NLP feature works without an LLM configured — keyword matching for queries, regex parsing for incident injection, template sentences for narration. This keeps the system functional for demo/dev without API keys.

2. **RL environment uses shadow state.** The Gymnasium env simulates minute-by-minute using a simplified shadow model (no Kafka, no Neo4j) so training can run thousands of episodes quickly. The shadow state is seeded from actual operational state.

3. **Anomaly detector retrains online.** Rather than a static pre-trained model, the IsolationForest retrains every 60 sim-ticks on the latest 2000 samples. This adapts to drift in simulation patterns (e.g., time-of-day effects).

4. **Single `AutonomousMode` enum replaces boolean toggle.** The old `enabled: true/false` is preserved for backward compatibility but the `mode` field is the authoritative source. `mode=off` ↔ `enabled=false`.

---

## What to watch for

- **Docker image size:** stable-baselines3 pulls in PyTorch (~2 GB). Consider `torch-cpu` only or a multi-stage build to slim down.
- **RL training requires episodes:** The `train_rl.py` script needs the simulation in BULK mode. Document the training workflow for the README.
- **LLM latency:** NL query and narration add LLM round-trip latency. The narration engine rate-limits to 1 generation per N ticks (default 10) to avoid overloading.
- **Anomaly cold start:** The detector produces no scores until 120 samples accumulate (~120 sim-ticks at 1 sample/tick). The API returns `status: "insufficient_data"` during warmup.

---

## Validation

- [x] `ruff check services/analysis-service/` — 0 errors
- [x] `npx tsc --noEmit` (dashboard) — 0 errors
- [x] `docker compose build analysis-service` — success
- [ ] Integration test with full stack (`docker compose up`) — pending manual verification

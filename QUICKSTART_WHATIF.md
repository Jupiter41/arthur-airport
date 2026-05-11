# Quickstart: ML Training & AI-Powered Operations

This guide explains how to train the RL (Reinforcement Learning) agent and
use the analysis & AI tools available in the Incidents page.

---

## Prerequisites

| Requirement | Detail |
|---|---|
| Stack running | `docker compose up -d` — all services healthy |
| analysis-service | Must be `Up (healthy)` — check with `docker compose ps` |
| Dashboard | Open `http://localhost:5173` |
| LLM (optional) | Set `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` in `docker-compose.yml` for richer NLP. Without it, template-based fallback works fine. |

---

## Part 1 — ML Training Page

Navigate to **ML & Agent Training** from the sidebar.

### 1.1 Training an RL Model (PPO)

The RL agent learns to make operational decisions (open/close security lanes,
hold/release flights, adjust baggage screening) by interacting with a
simulated airport environment.

**Step-by-step:**

1. **Select model type** — pick **RL Agent (PPO)** from the dropdown.
2. **Set timesteps** — default is 50 000. Higher values produce a better
   policy but take longer. Range: 1 000 – 1 000 000.
3. **Click "Start Training"** — a background subprocess is launched inside the
   analysis-service container.
4. **Watch the progress bar** — it updates every few seconds showing current
   vs total timesteps.
5. **Wait for completion** — the run appears in the **Training History** list
   with status `completed` and final metrics.
6. **Verify the model** — scroll to the **Trained Models** panel; the
   `rl_policy.zip` file should appear with its size and timestamp.
7. **Check the Environment panel** — "RL model file exists" should say **Yes**.

> **Tip:** You can also train **Anomaly Detector** or **Queue Forecaster**
> from the same dropdown. These currently run quick baseline routines rather
> than full training pipelines.

### 1.2 Enabling Autonomous Mode

Once a trained RL model exists, you can let the agent make operational
decisions automatically.

1. In the **Autonomous Operations** card, select a mode:
   | Mode | Behavior |
   |---|---|
   | **Off** | No autonomous actions |
   | **Rule-based** | Static if/then rules (no model needed) |
   | **Threshold** | Heuristic thresholds on KPIs |
   | **RL Agent** | Uses the trained PPO policy |
2. The **Recent Actions** feed shows what the agent decided and whether it was
   applied or safety-blocked.

### 1.3 LLM Configuration

The **LLM Config** card shows the current language-model connection status.
If `LLM_API_KEY` is not set, all NLP features fall back to keyword-based
template matching — functional but less conversational.

### 1.4 Environment & Models Panel

Displays runtime diagnostics:

- **RL model path** — file location inside the container.
- **File exists / Loaded** — whether the model is on disk and loaded in memory.
- **Model files** — lists all files in the `models/` directory.
- **Key env vars** — shows `RL_MODEL_PATH`, `LLM_BASE_URL`, etc.

---

## Part 2 — Incidents Page: Analysis & AI Tools

Navigate to **Incident Console** from the sidebar.

### 2.1 Operations Tab (Core Incident Management)

| Feature | Description |
|---|---|
| **Active Incidents** | Live list of `active` / `contained` incidents with cascade tree visualization |
| **Inject Incident** | Manually trigger a new incident (fire, security breach, medical, etc.) with preview of expected cascade effects |
| **Resolved Incidents** | History of past incidents with downloadable after-action reports |
| **Alert Feed** | Chronological stream of all incident-related alerts |
| **Export Dataset** | Download full incident dataset for offline analysis |

### 2.2 Analysis Tab

#### Bottlenecks

The analysis-service continuously monitors six operational dimensions:

- Security queue congestion
- Gate utilisation
- Baggage throughput
- Connection cluster risk
- Ground vehicle availability
- Runway capacity

Active bottlenecks appear ranked by severity.

#### Recommendations

For each detected bottleneck, the system generates ranked recommendations:

- **Description** — what action to take (e.g. "Open additional security lane")
- **Priority** — urgency rank
- **Expected impact** — projected improvement
- **Confidence** — model certainty (percentage bar)
- **Apply** — clicking this runs the recommendation through the What-If
  engine to preview its projected effect before committing.

#### What-If Simulation

Run hypothetical scenarios to see how actions would affect airport KPIs:

1. Select 1–3 actions (e.g. "open_security_lane", "hold_departures").
2. Set a projection horizon (5–120 minutes).
3. Click **Run**.
4. View projected KPI changes (passenger throughput, delays, queue lengths).

The What-If log keeps a history of all projections run during the session.

### 2.3 AI Tools Tab

#### Anomaly Detection

An Isolation Forest model monitors real-time operational metrics:

- **Status**: `normal` / `amber` / `red`
- **Scores**: raw and normalised anomaly scores
- **Root cause**: dominant feature contributing to the anomaly
- **Warmup**: requires ~120 data points before detection activates; a
  progress bar shows collection status

Refreshes every 30 seconds automatically.

#### Live Narration

A continuously-updated, human-readable summary of what is happening at the
airport:

- Toggle narration on/off with the enable button.
- Displays the most recent 20 narration entries.
- Uses LLM if configured; otherwise generates structured template narrations.

#### Natural Language Query

Ask questions about airport operations in plain English:

> *"What is the current average delay?"*
> *"How many passengers are in security?"*
> *"Which gate has the longest queue?"*

The system builds an operational context snapshot, sends it to the LLM (or
template matcher), and returns an answer with source attribution (`llm` or
`template`).

#### Natural Language Incident Injection

Describe an incident in natural language and the system parses it into a
structured injection command:

> *"There is a fire near gate B4"*

Returns the parsed incident type, zone, severity, and a preview of the
structured payload that would be sent to the incident-service.

#### After-Action Report

Generate a post-incident analysis report for any resolved incident. The
report includes timeline, cascade effects, response actions taken, and
lessons learned. Uses LLM for narrative quality when available.

---

## API Reference (for developers)

### ML Training Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analysis/training/status` | Current training job status |
| POST | `/api/v1/analysis/training/start?model_type=rl&timesteps=50000` | Start training |
| POST | `/api/v1/analysis/training/stop` | Stop active training |
| GET | `/api/v1/analysis/training/config` | Environment and model config |
| GET | `/api/v1/analysis/autonomous` | Autonomous mode settings |
| PATCH | `/api/v1/analysis/autonomous` | Update mode / threshold |
| GET | `/api/v1/analysis/autonomous/log?limit=10` | Recent autonomous actions |
| GET | `/api/v1/analysis/llm-config` | LLM connection status |

### Analysis & AI Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/api/v1/analysis/bottlenecks` | Active bottlenecks |
| GET | `/api/v1/analysis/recommendations` | Ranked recommendations |
| POST | `/api/v1/analysis/what-if` | Run what-if projection |
| GET | `/api/v1/analysis/anomalies` | Anomaly detection status |
| GET | `/api/v1/analysis/narration?limit=20` | Recent narration entries |
| PATCH | `/api/v1/analysis/narration` | Toggle narration on/off |
| POST | `/api/v1/analysis/query` | Natural language query |
| POST | `/api/v1/analysis/nl-inject` | Parse NL incident injection |
| POST | `/api/v1/analysis/report` | Generate after-action report |

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Training stuck at 0% | Check analysis-service logs: `docker compose logs analysis-service` |
| "Model not loaded" after training | Restart analysis-service or wait for lazy load on next RL evaluation |
| NLP returns generic answers | No LLM configured — set `LLM_API_KEY` in docker-compose.yml |
| Anomalies always "warmup" | Need ≥120 data points (~120 simulation ticks); let the simulation run longer |
| Recommendations empty | No active bottlenecks detected — inject an incident or increase traffic |
| Autonomous actions not appearing | Ensure mode is not "Off" and confidence threshold is met |

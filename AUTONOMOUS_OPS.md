# Autonomous Operations — User Guide

Arthur International Airport's digital twin can operate in **autonomous mode**,
where the analysis engine detects bottlenecks and applies corrective actions
without human intervention.

---

## Operating Modes

| Mode           | Description                                                                               |
| -------------- | ----------------------------------------------------------------------------------------- |
| **off**        | No autonomous actions. All recommendations require manual approval.                       |
| **rule_based** | Simple if-then rules (e.g. "if queue > 50 → open lane"). Fast, predictable, limited.      |
| **threshold**  | Applies any recommendation whose `confidence_score ≥ confidence_threshold`. Default mode. |
| **rl_agent**   | Reinforcement-learning agent trained on historical simulation data. Highest autonomy.     |

### Confidence Threshold

In `threshold` mode the system only applies actions with a confidence score at or
above the configured threshold (default: **0.80**, range: 0.50–1.00). Lower values
mean more aggressive intervention; higher values mean fewer but safer actions.

---

## How It Works

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Bottleneck │────▶│  Recommendation  │────▶│  Auto-Apply (if  │
│  Detection  │     │  Engine          │     │  confidence ≥ T) │
└─────────────┘     └──────────────────┘     └─────────────────┘
       ▲                                              │
       │            Kafka: AutonomousActionApplied    │
       └──────────────────────────────────────────────┘
```

1. **Detection** — Every `check_interval_sim_minutes` (default: 5), the engine
   scans live KPIs for anomalies: queue depths, gate conflicts, delay cascades.

2. **Recommendation** — For each bottleneck, ranked actions are generated (e.g.
   `open_security_lane`, `reassign_gate`, `redirect_baggage`).

3. **Decision** — Depending on the mode:
   - `rule_based`: hard-coded rules fire immediately.
   - `threshold`: only actions above the confidence threshold are applied.
   - `rl_agent`: the trained model picks the action with highest expected reward.

4. **Application** — The chosen action is published as a Kafka event
   (`AutonomousActionApplied`) and the relevant service reacts.

5. **Logging** — Every decision (applied or skipped) is recorded in the action log.

---

## Available Actions

| Action                   | Effect                                               |
| ------------------------ | ---------------------------------------------------- |
| `open_security_lane`     | Opens an additional security screening lane          |
| `early_gate_call`        | Calls passengers to gate earlier than scheduled      |
| `redirect_checkin`       | Redirects passengers to less-busy check-in desks     |
| `reassign_gate`          | Moves a flight to a different gate                   |
| `delay_taxi`             | Holds aircraft on taxiway to resolve runway conflict |
| `swap_gates`             | Swaps two gate assignments to reduce walking time    |
| `hold_connecting_flight` | Delays departure for connecting passengers           |
| `fast_track_passengers`  | Expedites processing for tight connections           |
| `rebook_passengers`      | Auto-rebooks passengers on missed connections        |
| `ground_delay_program`   | Implements GDP (**always requires human approval**)  |
| `redistribute_vehicles`  | Rebalances ground vehicles across terminals          |
| `defer_task`             | Postpones a low-priority ground task                 |
| `redirect_baggage`       | Reroutes baggage to alternate carousel/belt          |
| `expedite_loading`       | Prioritises loading for a departing flight           |

### Blocked Actions

Some actions are too impactful for full automation.
`ground_delay_program` is blocked by default — it always surfaces for human
confirmation regardless of confidence score.

---

## LLM Integration

The analysis service optionally connects to an LLM for:

| Feature                    | Endpoint                   | Purpose                                                                  |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------ |
| **Natural language query** | `POST /analysis/query`     | Ask questions about airport state in plain English                       |
| **NL inject**              | `POST /analysis/nl-inject` | Describe a scenario in natural language → actions are parsed and applied |
| **Anomaly narration**      | `GET /analysis/narration`  | LLM generates a human-readable summary of current anomalies              |
| **Report generation**      | `POST /analysis/report`    | Produces a structured ops report for a time window                       |

---

## Configuration (API)

```bash
# View current settings
curl http://localhost:3000/api/v1/analysis/autonomous

# Enable threshold mode at 0.75 confidence
curl -X PATCH http://localhost:3000/api/v1/analysis/autonomous \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "mode": "threshold", "confidence_threshold": 0.75}'

# View action log
curl http://localhost:3000/api/v1/analysis/autonomous/log?limit=20
```

---

## Configuration (Dashboard)

In the React dashboard, open **Incidents → AI Tools** (or **ML Training → Autonomous**)
to toggle the mode, adjust the threshold, and review the action log in real time.

---

## Training the RL Agent

When `mode = rl_agent`, the system uses a LightGBM model trained on historical
simulation episodes. Training is managed via:

```bash
POST /analysis/training/start   # begin a training run
POST /analysis/training/stop    # abort training
GET  /analysis/training/status  # check progress
GET  /analysis/training/config  # view hyperparameters
```

Training data is generated automatically during simulation runs and stored in Neo4j.

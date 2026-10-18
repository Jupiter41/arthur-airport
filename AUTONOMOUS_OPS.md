# Autonomous Operations — User Guide

> **Verification update (2026-10-18):** see `ROADMAP_REAL_LDT.md` §10 for
> delivered behavior, validation boundaries and open gaps. Planning records now
> persist in Neo4j; owner receipts confirm action execution. Automatic measured
> savings, full action coverage and a unified effect/recommendation engine remain
> incomplete. Passing functional tests does not establish calibrated benefit.


Arthur International Airport's digital twin can operate in **autonomous mode**,
where the analysis engine detects bottlenecks and submits supported corrective
actions through guarded owner commands. Some actions require human approval.

---

## Operating Modes

| Mode           | Description                                                                               |
| -------------- | ----------------------------------------------------------------------------------------- |
| **off**        | No automatic proposals; operators can submit supported recommendations manually. |
| **rule_based** | Proposes all eligible concrete recommendations that pass configured gates. |
| **threshold**  | Proposes the first eligible recommendation above the configured score threshold per cycle. |
| **rl_agent**   | A loaded PPO policy selects an action type, then the same concrete-target and safety gates apply. |

### Confidence Threshold

In `threshold` mode the system only applies actions with a confidence score at or
above the configured threshold (default: **0.80**, range: 0.50–1.00). Lower values
permit more candidates; higher values permit fewer. Recommendation scores are
heuristics, and policy probabilities are not calibrated probabilities of a safe
or beneficial outcome.

---

## How It Works

```
Domain facts → Detection → Recommendation → Approved proposal
                                                ↓
Owner command → Owner mutation → CommandExecuted receipt
                                      ↓
                         AutonomousActionApplied + execution log
```

1. **Detection** — On processed simulation ticks, the engine evaluates queue
   depths, gate conflicts and delay cascades. Autonomous decisions run at
   `check_interval_sim_minutes` (default: 5).

2. **Recommendation** — For each bottleneck, ranked actions are generated (e.g.
   `open_security_lane`, `reassign_gate`, `redirect_baggage`).

3. **Decision** — Depending on the mode:
   - `rule_based`: eligible recommendations pass score, safety and cooldown gates.
   - `threshold`: the first eligible recommendation proceeds per cycle.
   - `rl_agent`: the policy selects an action type, matched to an eligible concrete
     recommendation. No policy or concrete target means no action.

4. **Execution** — An approved concrete proposal is dispatched on the owner's
   `*.commands` Kafka topic. Only its `CommandExecuted` receipt marks it executed
   and emits `AutonomousActionApplied`. A rejection marks failure. Dispatch alone
   does not prove execution, and unsupported actions remain advisory.

5. **Logging** — Proposal lifecycle records persist in Neo4j. The confirmed action
   log is rebuilt from executed proposals; skipped candidates are not a complete
   durable decision log. Automatic outcome measurement remains planned work.

---

## Executable and advisory actions

The following mappings execute only when a recommendation supplies the required
concrete target and valid parameters. Aggregate suggestions may lack these inputs
and remain advisory (Apply returns 422).

| Action | Required inputs and implemented command |
|---|---|
| `open_security_lane` | Terminal and lane count; `OpenSecurityLane` sets that count. |
| `reassign_gate` | Flight ID and gate ID; `ReassignGate` moves the assignment. |
| `delay_taxi`, `hold_connecting_flight` | Flight ID and positive duration; `HoldFlight` applies a hold. |
| `redirect_baggage` | Bag ID and target flight ID; `RedirectBaggage` changes the bag's flight. |

`early_gate_call`, `redirect_checkin`, `swap_gates`, `fast_track_passengers`,
`rebook_passengers`, `ground_delay_program`, `redistribute_vehicles`, `defer_task`
and `expedite_loading` have no executable mapping. Their advertised intervention
effects remain design intentions, rather than implemented owner behavior.

### Blocked Actions

Some actions are too impactful for full automation.
`ground_delay_program` and `rebook_passengers` require human review regardless of
score when settings allow them to be proposed. Operator-blocked actions are
skipped. Both guarded actions still lack owner command handlers, so approving
them cannot make them executable.

---

## LLM Integration

The analysis service optionally connects to an LLM for:

| Feature                    | Endpoint                   | Purpose                                                                  |
| -------------------------- | -------------------------- | ------------------------------------------------------------------------ |
| **Natural language query** | `POST /analysis/query`     | Ask questions about airport state in plain English                       |
| **NL inject parser**       | `POST /analysis/nl-inject` | Returns structured incident parameters; injection is a separate operation |
| **Anomaly narration**      | `GET /analysis/narration`  | LLM generates a human-readable summary of current anomalies              |
| **Report generation**      | `POST /analysis/report`    | Produces a report from the current operational state and active records |

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

When `mode = rl_agent`, the system uses a Stable-Baselines3 PPO policy trained in
the synthetic `AirportOpsEnv`. It requires a usable policy artifact. LightGBM is
used separately for passenger queue forecasting. RL training is managed via:

```bash
POST /analysis/training/start   # begin a training run
POST /analysis/training/stop    # abort training
GET  /analysis/training/status  # check progress
GET  /analysis/training/config  # view hyperparameters
```

RL training generates episodes inside its environment; it does not replay Neo4j
operational history. The artifact creation/reload tests prove the training path
works, not that the policy is calibrated or improves airport outcomes. This API
supports `rl` training; requests for forecast/anomaly training return 422.

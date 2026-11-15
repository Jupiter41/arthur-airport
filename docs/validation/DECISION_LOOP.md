# Decision-loop implementation and local validation

Validated on 2026-11-14 against a disposable `art-decision-validation` Compose
project with fresh volumes and synthetic data. Existing cached service images
were used with current source mounted; no data volumes were pruned or reset.

## Evidence contract audit

| Stage | Durable source | Correlation |
| --- | --- | --- |
| Detection | DecisionRecord.bottleneck | bottleneck ID, optional incident ID |
| Prediction | Recommendation projection snapshot; dispatch baseline.predicted | recommendation/proposal ID, model version |
| Ranking and reasoning | ActionProposal.decision_context | immutable selected recommendation and ranked alternatives |
| Authorization | proposal history and decision fields | approver, simulation timestamp |
| Dispatch | proposal history and transactional outbox | command ID = proposal ID, attempt number |
| Execution/rejection | validated owner_receipt and lifecycle history | expected command type and owning Kafka topic |
| Measurement | actual_outcome and measurement history | prediction, treated/control observations, eligibility |

The gateway adds no business logic. Analysis never writes passenger-owned state.
The timeline distinguishes queued delivery, owner-confirmed execution and later
measurement. Older proposals without snapshots/receipts remain visibly incomplete.

## Reproduce the teaching slice

Use a disposable local stack and start it through `python scripts/docker_storage.py up`.
Wait for readiness and a simulation clock tick. Supply an approver's credentials
through `ART_CLIENT_ID` / `ART_CLIENT_SECRET`, or an `ART_API_TOKEN`; do not put
credentials in the output or commit them. Finish existing active proposals first.

```powershell
python scripts/teach_security_loop.py --output tmp-security-lesson.json
python scripts/replay_effects.py --output tmp-decision-replay.json
```

The runner refuses public control-enabled deployments and nonlocal URLs. It
pauses the lab, disables autonomy, configures owner lanes A=1/B=4/C=4, injects
synthetic queues A=450/B=180/C=180, submits an executable recommendation for
human approval, and waits for receipt and measurement. If needed, it creates
future synthetic departures via the existing debug injection route.

Lane setup uses gateway `POST /api/v1/passengers/flow/security/{A|B|C}/lanes`
with strict integer `lanes_open` and optional idempotent `command_id`. The
passenger owner uses its existing atomic state/fact/receipt/outbox handler;
sim-orchestrator lane settings alone do not change passenger-owned checkpoints.
This local write endpoint is denied by the public gateway allowlist.

The runner restores original lane counts, autonomy, settings, speed and pause
state in `finally`; it reports restoration errors. Injected passengers/flights
and decision evidence remain in the disposable lab. It does not reset/delete
data. Missing execution, measurement, fresh controls or attribution fails the run.

## Actual outcome

[Exported live evidence](security-lane-teaching.json) records decision
`prop-95c232728b74`: owner execution at 11:12 simulation time and measurement
at 11:42. Predicted wait change: **-111.35 min**; observed treated change:
**-89.40 min**; attributed effect: **-79.15 min**, using two fresh untreated
comparison terminals. No control-terminal interventions occurred during the
window and restoration errors were empty. Negative wait change is improvement.

The receipt, immutable rationale, baseline and outcome remained available after
analysis-service restart. Desktop/mobile browser checks covered deep-link
selection, recorded-stage playback and return to latest. Historical mode hides
future evidence and disables mutations. [Screenshot](decision-timeline.png).

[G4 replay](decision-loop-replay.json) finds one eligible security sample,
40.69% median absolute relative error and **unvalidated** status. Twenty samples
and at most 25% median error are required. This run proves the pipeline and
evidence presentation; it does not establish accuracy or randomized causality.
The proposal's ranking snapshot correctly shows zero samples at proposal time.

## Checks

- Python unit suite excluding the separate RL smoke module: 1,296 passed.
- Dashboard: 46 tests passed; production build passed.
- Gateway: 33 tests passed; TypeScript build passed.
- Ruff checks passed for new history, timeline models/router, lane endpoint,
  teaching runner and their tests.
- Existing deprecation, stale Browserslist and large bundle warnings remain.

Full coordinated simulation rewind remains deferred under NEXT_STEPS.md.
The recorded-decision cursor does not restore or rerun airport state.

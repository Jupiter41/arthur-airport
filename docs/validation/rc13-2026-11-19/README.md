# RC13 settings contract validation

Started 2026-11-19; completed 2026-11-20 (Europe/Luxembourg).
Implementation: `69e90b7`, on baseline `16f14dc`.

**RC13 is closed.** RC14 rollout and RC15 broader CI remain separate.

## Changes

Initial lane, screening-count and sorting preferences derive from the shared
airport configuration. Saved preferences retain their flat compatibility fields
and gain an explicit `requested` document and per-field `application` modes.
The gateway independently reads passenger and baggage owners for `effective`
values and their simulation times. Missing or malformed owner responses produce
unknown effective values; requested defaults never replace them.

The settings page shows applied lanes separately from requested lane commands.
Commands use the existing durable passenger-owner control and stable IDs for
lost-response retries. Baggage capacities and MCT are read-only owner observations.
Daily demand/hourly weights are labelled as requests for future manifests.
Legacy preferences without consumers are labelled `stored_only` and have no
Apply action. Owner configuration/restart requirements are explicit. Public
operator restrictions remain unchanged.

## Evidence

- [Python unit suite](unit-results.txt): **1,496 passed**.
- [Gateway suite](gateway-tests.txt): **44 passed**.
- [Dashboard suite](dashboard-tests.txt): **117 passed**.
- [Gateway compilation](gateway-build.txt), [dashboard production build](dashboard-build.txt), and [Ruff](lint.txt): passed.
- [Guarded image builds](guarded-build-summary.txt), [normal compose startup](startup.txt), [live probe](live-results.txt), [reproducible probe source](validate.py), and [image/source fingerprints](image-fingerprints.json).

| Check | Observed result |
| --- | --- |
| [Fresh startup](cold-start.json) | Requested and effective lanes 8/12/8; sorting 5,400 bags/hour; six screening units |
| [Saved stale preferences](saved-preferences.json) | Requested lanes 4/3/4 and sorting 1,800 remain distinct from unchanged owner observations |
| [Owner application](owner-applied.json) and [receipts](lane-receipts.json) | Explicit lane command applies A=3; retry of the same command ID with A=9 returns the stored receipt and does not reapply |
| [Durable restart](durable-restart.json) | Orchestrator preferences and pause/clock restore; owner A=3 survives; stale requested values never overwrite owner state |
| [Owner outage](owner-unavailable.json) | Stopped baggage owner yields `unavailable` and null values, never the saved 1,800 preference |
| [Future manifest application](manifest-application.json) | Existing day remains 60 flights; new daily request of 80 produces 80 owner flights on the next day |

The final probe uses a new `art-rc13-verified` compose project with fresh volumes,
normal startup/control/restart paths, real Neo4j/Kafka and guarded built images.
There are no service-source overlays, manual graph changes, skipped assertions,
or disabled recovery/watermark controls. The ordinary shared-library/config
mounts from the base compose file remain. All changed Python source hashes are
compared to the checkout; built gateway JavaScript is compared to the local
TypeScript build. Image IDs are recorded for all five changed services.
The validation uses 60 initial daily flights to bound workload, then verifies an
80-flight future manifest through normal owner application.

## Reproduce

From the repository root, build using the storage guard, compile the gateway to
`/tmp/rc13-gateway-dist`, then start an unused isolated project:

```bash
.venv/bin/python scripts/docker_storage.py build passenger-service baggage-service sim-orchestrator api-gateway dashboard
(cd services/api-gateway && npm run build -- --outDir /tmp/rc13-gateway-dist)
docker compose -p art-rc13-verified -f docker-compose.yml -f docs/validation/rc13-2026-11-19/compose.override.yml up -d --no-build
.venv/bin/python docs/validation/rc13-2026-11-19/validate.py
docker compose -p art-rc13-verified -f docker-compose.yml -f docs/validation/rc13-2026-11-19/compose.override.yml down
```

For a subsequent cold-start run, choose an unused project and set `RC13_PROJECT`
to that compose project name before running the probe; preserve existing volumes.
The probe mutates only this isolated fake airport through its authorized APIs.
The validation stacks were stopped after the checks; all volumes were preserved.
RC14 still tracks deployment to the existing airport and RC15 tracks the broader
built-image CI gate. This evidence closes the RC13 configuration contract only.

# RC14 coherent deployment and legacy disposition

Completed 2026-11-20 (Europe/Luxembourg). **RC14 is closed.**
Original deployment: `art-ldt-g6`, using its existing Neo4j/Kafka volumes.
Migration/identity implementation: `18dc090`; final runtime cohort:
`04038a42ce314584137291bf5b158ddf1a3a11e4`.

## Result

All eleven application images carry a clean common revision, actual source and
runtime artifact digests, shared-code digest and configuration digest. Shared
code and configuration are baked into images; the default/Pi compose profiles
no longer hot-mount them. Python and gateway `/build` endpoints expose integrity;
the frontend serves `/build.json` with its emitted artifact inventory. Readiness
rejects mismatched artifacts/contracts and mixed owner revisions. The rollout
uses immutable image tags and a recorded image-ID lock.

- [Deployment lock](deployment-lock.json), [rollout profile](rollout.compose.yml).
- [Initial final-cohort verification](deployed-builds-before.json) and
  [post-restart verification](deployed-builds-final.json): **11/11 verified**.
  Every frontend artifact was fetched and checked against its recorded SHA-256.
- [Live validation](live-validation.json), [initial run log](live-results.txt),
  [remaining restart check](restart-final-results.txt), and
  [reproducible audit](validate_deployment.py).
- [Restored operator profile](profile-restored.json): **420 flights/day, 60x,
  running**. The airport remains deployed, with no data reset.

## Original data and disposition

[Pre-rollout audit](legacy-before.json) records simulation day 47,
2024-07-31 07:55, with **659,872** live/archived bags lacking `passenger_id`.
The old graph had no SeedDay. Before mutation, the stopped Neo4j data volume was
copied read-only to a compressed snapshot in volume
`art-rc14-rollback-20261120`, file `/backup/neo4j-data.tgz`.
[Snapshot checksum](rollback-snapshot.txt):
`bf1f9131a014579272b0d4720f51bd9dc91d98c3bc0d51f13f2861794b0b9dee`.
This is a graph snapshot, not a claim of an atomic graph/broker backup pair.

Baggage-service performed the migration before queue reconstruction:

| Disposition | Bags | Policy |
| --- | ---: | --- |
| Proven existing identity | 326,005 | Backfill only the unique passenger ID already proved by CARRIES |
| Unprovable identity | 333,867 | Preserve as LegacyBaggage with original label/status, properties, scans and relationships |
| Invented passenger identities | 0 | Never generate a passenger or infer an anonymous bag's owner |

The quarantine leaves live/archive indexes and ordinary retention. Its scans
remain LegacyScanEvent; its barcodes remain reserved by the monotonic allocator.
There is no automatic quarantine purge. Every classification batch commits its
identity/label changes, counters and BaggageIdentityDisposition outbox fact in
one transaction. Repeated owner startup does not reclassify completed records.
Known historical entities continue to follow their existing retention policy.

The initial coherent cohort applied this migration; its
[record](initial-cohort-live-validation.json) and
[build verification](initial-cohort-deployed-builds-before.json) are retained.
The final cohort adds coverage for compiled JSON contracts without changing the
migration policy. No database, Kafka volume or consumer offsets were reset.

## Live checks on the original deployment

| Check | Observed result |
| --- | --- |
| Durable clock | Existing day 47 retained; no rewind to day one |
| Stale shared overlay | Passenger and gateway readiness return 503; restored file state verifies |
| Mixed owner revision | Gateway readiness returns 503; original manifest restored |
| Changed compiled JSON policy | Gateway runtime integrity and readiness reject it; exact original bytes restored |
| Six-hour owner outage | 2024-07-31 09:27 to 15:29; both flow owners stopped through normal Compose controls |
| Moving-clock recovery | 371.43 seconds at 60x; baggage/passenger lag 0, flight lag 1 minute; no operator resume needed after owner restart |
| 23:30/midnight seeding | Next-day ready SeedDay, all owner seed batches accepted, new day reached |
| New-day owner cohort | 60 flights, 9,523 passengers, 8,422 bags; membership observed from real owner Kafka seed facts, including partition/offset evidence |
| Identity links | All 8,422 new bags linked to their named passenger; zero invalid links |
| Arrival/transfer flow | 805 passenger transfers, 714 transfer bags; zero airborne passengers on scheduled arrivals |
| Pickup | 3,070 claim exits, including 1,803 before the 45-minute timeout |
| Collection durability | 1,896 passenger-keyed collected observations retained across passenger/baggage/orchestrator/gateway restart; exact paused clock restored |
| Final integrity/readiness | All eleven images verified; all nine upstream readiness/identity checks true |

The normal settings API temporarily requested 60 future daily flights to bound
the new-day cohort. Existing legacy flights were not rewritten. Original demand,
speed and running state were restored through the same APIs after validation.
Watermark backpressure, bounded recovery, retention, Kafka delivery and owner
startup paths remained enabled. There were no production fixture writes or
application patches in containers. The three reversible filesystem changes were
explicit integrity-failure probes and were restored before accepting the cohort.

The first auditor used bag IDs for PassengerBaggageObservation, whose key is a
passenger ID. Arrival/transfer/link checks had already passed. The auditor was
corrected to the actual owner contract and the remaining restart check resumed
against the same frozen deployment/cohort. [First attempt](initial-audit-results.txt)
and the correction in live-validation.json are retained. No application behavior
or assertion was bypassed.

## Regression and build evidence

- [Python unit suite](unit-results.txt): **1,498 passed**, eight existing warnings.
- [Gateway suite](gateway-tests.txt): **47 passed**, including mixed-build and
  changed compiled JSON rejection; [TypeScript compilation](gateway-build.txt).
- [Real Neo4j migration test](legacy-transaction-results.txt): **1 passed**,
  covering outbox-failure rollback, bounded batches, repeat startup, relationship
  proof, retained scans and quarantined barcode reservation. Its stable source is
  [tests/rc14_transactions/test_legacy_identity.py](../../../tests/rc14_transactions/test_legacy_identity.py).
- [Required Ruff scope](lint.txt): passed.
- [Guarded build summary](guarded-build-summary.txt): all application images
  built with clean revision stamps; full build logs were inspected during rollout.
- [Rollout startup](rollout-startup.txt). Kafka's preserved log initially exceeded
  the old probe budget; [initial warmup](initial-infra-warmup.txt) is retained.
  The rollout profile budgets 180 seconds for Kafka/domain startup and 900 for
  bounded legacy baggage migration. Health/readiness are not forced successful.
- CI now uses the storage guard to stamp its builds, verifies the full cohort,
  and runs the real migration test in a dedicated isolated database job. This
  prevents the isolated test from running against a general integration airport.
  These workflow changes are structurally checked; this report does not claim a
  remote CI result or close RC15's broader gate.

The isolated migration test database was stopped with its volume preserved.
The original airport and rollback snapshot remain available. No remote Raspberry
rollout is claimed by this local deployment finding.

## Reproduction and operations

Use the storage guard for a new clean cohort, retain its generated
`.art-build-manifest.json`, pin its image tags/IDs in the rollout profile, and
preserve existing volumes. Verify this deployed release with:

```bash
.venv/bin/python scripts/verify_builds.py --project art-ldt-g6 \
  --manifest docs/validation/rc14-2026-11-20/deployment-lock.json \
  --revision 04038a42ce314584137291bf5b158ddf1a3a11e4 \
  --report /tmp/rc14-build-verification.json
```

`validate_deployment.py` performs real simulation controls and a six-hour owner
outage. Run it only in an authorized maintenance window, followed by
`restore_profile.py` to restore the recorded operator profile. Its documented
`--resume-restart` mode completes the recorded frozen cohort's restart stage.
The snapshot, retained quarantine and original volumes must not be automatically
pruned. RC15-RC20 remain tracked separately.

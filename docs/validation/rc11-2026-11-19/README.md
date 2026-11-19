# RC11 resilience closure validation

Date: 2026-11-19 (Europe/Luxembourg). Fix checkpoint: `4dd4740` on baseline `69f7f78`.

**RC11 is closed.** Remaining poison-message policy and rollout work stay under RC16 and RC14.

## Scope and changes

The original bounded recovery queries, five-minute passenger/baggage catch-up,
Neo4j memory settings and background 23:30 seeding remain in place. RC7/RC8/RC12
and their stale validation fixtures were closed separately. RC16 still tracks
general poison-message quarantine/retry policy; this report does not close it.

Two additional failure paths were fixed for RC11:

1. Clock checkpoint auto-commit results are now explicitly consumed within the
   transient retry block. Neo4j session cleanup can suppress a late result or
   commit exception; the old code could acknowledge an unconfirmed checkpoint.
   A lost acknowledgement retries the same idempotent snapshot. Exhausted or
   non-transient failures pause without emitting a successful control receipt.
2. The midnight seeding barrier now runs before advancing into the new day or
   invoking that minute's callbacks. Failure leaves the clock on the last valid
   minute, checkpoints/publishes `day_seed_failed`, and emits only an already
   advanced valid prefix of a multi-minute tick. Resume retries the same barrier
   even after its failed task was consumed. No new-day tick is emitted unseeded.

## Evidence

- [Python unit suite](unit-results.txt): **1,493 passed**, eight existing warnings.
- [Real Neo4j/Kafka RC11 gate](transactions.xml): **7 passed**, zero skipped.
- [Detailed transaction/profile results](transaction-results.txt).
- [Existing full-stack restart/rebuild suite](restarts.xml): **6 passed**, zero skipped.
- [Final readiness after restart checks](final-readiness.json): all ten endpoints returned 200.
- [Required service/live-transaction Ruff scope](lint.txt): passed.

The transaction gate uses cached dependency images, current owner sources, real
Neo4j transactions and actual Kafka control publication in independent processes.
A durable test marker inside each transaction records its committed simulation
time; it cannot survive rollback independently of the owner tick.

| Regression | Result |
| --- | --- |
| Six-hour passenger backlog | 72 commits, every step at most 5 sim-minutes |
| Six-hour baggage backlog | 72 commits, every step at most 5 sim-minutes |
| Failure in fourth transaction, followed by process death | First three commits survive at 12:15; failed fourth rolls back; new worker reaches 18:00 |
| Replay of completed target | No duplicate progress, facts or marker records |
| Two lost commit ACKs after actual Neo4j commits | Third attempt confirms the same snapshot; one real Kafka control event; no pause |
| Retry exhaustion after three lost ACKs | Paused; no successful control event |
| Passenger recovery PROFILE with 40,000 unrelated history entities | 6 DB hits; zero returned candidates |
| Baggage induction PROFILE with the same history | 17 DB hits; one eligible bag |
| Real midnight callback after background and inline failures | Error reaches clock; later call retries the consumed task and succeeds |

Transport ACK failures are explicitly injected after real database commits; this
is an uncertain-commit regression, not a claim to reproduce an actual OOM. Query
profiles demonstrate bounded unrelated-history work for these fixtures, not a
new multi-million-node memory benchmark. Existing 2G/2G production Neo4j defaults
are retained; the small G1 fixture uses 512 MiB heap/cache.

The clock unit regressions additionally prove late-consumption retry, exhausted
late failures with no control ACK, nonblocking background seeding and failed
midnight barriers for one- and six-minute ticks. They verify contiguous minute
callbacks, correct day counters, actual partial step lengths, and retry on resume.

## Full-stack interruption and recovery

[Live recovery record](live-recovery.json), [probe output](live-results.txt).
The isolated current-source stack recovered from a two-wall-second Neo4j pause
without an automatic clock pause or operator resume. Its two stopped flow owners
accumulated **6 hours 8 minutes** of lag (02:37 checkpoints against 08:45).
After restart at the normal 60x tick budget, every owner reached within five
minutes of the moving clock in **37.47 wall seconds**. Only then did the probe
pause deliberately for convergence: all three checkpoints equal **09:34**.
All ten readiness endpoints returned 200.

The fresh project's complete Kafka clock stream contains **2,049 ticks** with
contiguous simulated minutes, including 23:30 and midnight. Clock, passenger and
baggage logs contain no OOM or automatic checkpoint/day-barrier pause markers.
The existing integration restart suite subsequently restarted individual owners
and the entire stack; all six checks passed. CI explicitly builds the clock
worker image used by the new fault tests. The raw record includes seed times and the original near-midnight startup. It
also retains the earlier high-speed attempt in the clock stream; only the final
corrected 60x recovery is timed as the current-clock convergence result.
This is a functional recovery workload at 60 movements/day, not a 420-movement
high-speed performance certification. No poisoned input was silently skipped.

## Reproduction

From the repository root, with the previous validation configuration files and
available cached runtime images (use the Docker storage guard for any build):

```bash
export ARTHUR_REPO_ROOT="$PWD"
export COMPOSE_PROJECT_NAME=art-rc11-g1
export COMPOSE_FILE="$PWD/docs/validation/rc7-rc8-2026-11-19/g1.compose.yml"
docker compose up -d neo4j kafka
docker compose run --rm --no-deps kafka-init
G1_DISPOSABLE_STACK=1 python -m pytest tests/live_transactions/test_rc11_resilience.py -q -rP
python -m pytest tests/unit -q
ruff check services tests/live_transactions scripts/validate_rc11.py
```

These fixtures refuse foreign operational flights and must never target an
airport graph. For full-stack validation, use the source overlay from the prior
report with `SIM_START_TIME=2024-06-15T23:25:00`, speed 600x and the validated
60-movement/day functional workload. `scripts/validate_rc11.py` pauses Neo4j for
two wall seconds, stops the passenger/baggage owners for at least six sim-hours,
then restarts them with recovery at the normal 60x tick budget. The recovery
condition requires every owner to reach the **current** clock within five minutes;
reaching only the original outage target cannot pass. Only after convergence
does the probe pause for an exact checkpoint snapshot.

The first discarded live attempt used 600x recovery and initially tested an old
absolute target rather than convergence. Its replay did drain, but that attempt
is not presented as an automatic current-clock recovery or throughput result.
The corrected run uses 600x only to accumulate the outage, with 60x recovery.
No application workaround, volume reset, global pruning or existing-airport
rollout is part of this validation. RC14 continues to track deployment identity.

Both owned validation projects were stopped after verification; all volumes were preserved.

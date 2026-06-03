# Sprint 50 — Stabilize architecture & improve business value

## Goal

PROMPT.md task: read all roadmaps and SPECs, hunt gaps, refactor duplicates, brainstorm
improvements (→ PLAN.md), and harden the cost / planning models so users can trust the
numbers.

## Deliverables

- `PLAN.md` (root) — living brainstorm, organised by topic (cost model, planning model,
  cross-cutting hygiene), each split into Landed (P0) / Proposed (P1) / Proposed (P2).
- 11 P0 fixes across cost-service, planning-service, incident-service and the dashboard
  Investment tab.
- This summary.

## Bugs fixed along the way

### cost-service

1. **Magic constants in `cost_engine.py`** — peak-hour set, security-lane counts,
   bags-per-pax ratio and check-in desk counts were hard-coded. Extracted to
   `fixtures/cost_rates.json` under a new `operations` block. `on_clock_tick` and
   `on_flight_status_changed` now read from there.
2. **Routes returned HTTP 200 with an error JSON when Neo4j was down.** Introduced a
   `_require_neo4j()` helper that raises `HTTPException(503, …)` and applied it to
   `/pnl`, `/flight/{id}`, `/incident/{id}`, `/terminal/{id}`. `/hourly` now degrades
   gracefully to 24 zero-padded buckets so the dashboard never sees a partial array.
3. **`/ready` was 200 even when not ready.** It now flips the response status to 503
   when the engine has not connected.
4. **`PATCH /rates` accepted arbitrary deep merges**, including unknown top-level keys
   and silent type changes (e.g. dict→string). Now validates allowed keys and that
   leaves keep their type (int↔float allowed, everything else rejected with 400).
5. **`/incidents/ranking` mislabelled EU261 cost as `response_eur`.** Added explicit
   `eu261_eur` field; kept `response_eur` as alias for backward compatibility.

### planning-service

1. **`total_flights` was never aggregated** by `_collect_kpis`, so the benefit
   extractor silently fell back to a hard-coded 420 flights/day default. Added the
   key, so investment cases now reflect the real simulated volume.
2. **IRR returned 100.0 % when the cashflow had no sign change.** That is wrong: a
   series with no negative→positive flip has no real IRR. `_compute_irr` now returns
   `(rate, meaningful: bool)`. `InvestmentResult.irr_meaningful` propagates and
   serialises `irr_pct` as `null` when not meaningful. The recommendation gate falls
   back to NPV-only in that case.
3. **`sensitivity_analysis` averaged the benefit then ran an annuity formula**, which
   destroys the growth shape and gives misleading optimistic/pessimistic NPVs. Rebuilt
   to a year-by-year DCF: explicit per-year cashflow `-capex, then annual_benefit *
   (1+g)^(yr-1) - opex`, NPV via discounted sum, payback via walking the actual
   series, IRR via the same robust solver — for every scenario.
4. **`demand_multiplier` on `Scenario` was accepted but never used.** Engine now takes
   it as a kw-only arg in `run_day` and a helper scales `pax_count` linearly, with
   schedule expansion (duplicate flights with `D###` suffix) when growing and a
   shuffled slice when shrinking.
5. **`weather_source` on `Scenario` was accepted but never used.** Runner now builds a
   second adapter via `get_weather_adapter(scenario.weather_source)` (only when it
   differs from the schedule source) and the engine consumes it for the weather
   sequence; the schedule adapter remains the source for flights.

### incident-service

1. **`TTR_RANGES["security_congestion"]` was `(15, 60)` minutes** — but the SKILL spec
   and the unit test both require `None` because security congestion auto-resolves
   when the queue drains, not on a countdown. Restored to `None` and kept the comment
   anchored to the passenger-service signal.

### Doc drift

1. `docs/roadmaps/ROADMAP3.md` referenced cost-service on port 8007. Actual port is
   8008. All occurrences updated.
2. `docs/roadmaps/ROADMAP4.md` referenced planning-service on port 8008. Actual port
   is 8009. All occurrences updated.

### Dashboard

1. `InvestmentTab.tsx` rendered IRR as `0.0 %` when the backend now returns `null`,
   and the colour gate would have crashed on `(null) > x`. Now shows `n/a` with the
   explanation "No real IRR (cashflow has no sign change)" and a neutral colour when
   `irr_meaningful === false`.

## Tests run

| Suite | Result |
|---|---|
| `ruff check services tests scripts` | All checks passed |
| `pytest tests/unit -q` | **722 passed** in 2.50s |
| `npm --prefix dashboards/art-dashboard run build` | **built in 7.74s** (only chunk-size warnings, no TS errors) |

The previously-pre-existing failure in
`tests/unit/test_incident_lifecycle.py::TestTTRRanges::test_security_congestion_no_ttr`
is now green as part of the incident-service fix above. Confirmed on a `git stash`
that this failure existed on `main` HEAD before this sprint and was not introduced by
the changes here.

## Lessons learned

- **Magic constants in business engines are landmines.** They prevent ops tuning
  without a redeploy and they hide assumptions. Always externalise to the rates /
  config fixture even when they "feel obvious".
- **HTTP shape matters as much as the JSON.** A 200 with `{"error": …}` defeats the
  whole point of HTTP semantics — clients/dashboards don't even know to treat it as
  a failure. Use 503 for "dependency down", 400 for input validation, full stop.
- **IRR has a "no real IRR" case** (no sign change in cashflow). Returning a sentinel
  number is silently wrong; a `meaningful` flag with `null` payload is the correct
  shape.
- **DCF beats annuity for growing benefits.** The convenience of the annuity formula
  is not worth the wrong answer when growth_rate ≠ 0.
- **Spec drift is always free until it isn't.** Three doc-vs-code mismatches found
  this sprint (port 8007/8008/8009, security_congestion TTR). Worth a CI grep job.
- **Scenario knobs that don't do anything are worse than no knobs** — they create
  trust debt. Either wire the field through the engine or remove it from the schema.

## Follow-ups deferred to PLAN.md (P1 / P2)

See `PLAN.md` for the full list. Highlights:

- Eurocontrol Standard Inputs constants are still duplicated between
  cost-service and planning-service — extract to `services/_common`.
- Gate fee / parking fee revenue path (referenced by docs, not yet wired into the
  P&L consumer).
- OpenSky stub adapter (so `weather_source="opensky"` etc. fail loudly in dev rather
  than silently degrading to historical replay).
- Scenario persistence to Neo4j (currently in-memory).
- `new_routes` field in scenarios is not yet consumed by the engine.

# Sprint 53 — P2 Planning & Cross-cutting Hygiene

**Date:** 2026-06-08
**Scope:** PLAN.md §2 P2 (planning model) + §3 P2 (cross-cutting hygiene)

---

## Summary

Implemented all five P2 items from PLAN.md:

1. **Counterfactual replay (1B)** — already fully implemented in prior sprints;
   marked as complete.
2. **Slot allocation simulator (2B)** — new ILP-based engine using PuLP with
   three strategies (FCFS, priority-weighted, optimised) and schedule compression.
3. **Network resilience tab (2D)** — Herfindahl-Hirschman Index hub dependency
   scoring, airline disruption simulation, and gravity-model diversification
   recommendations using BTS T-100 data.
4. **End-to-end smoke test in CI** — new `e2e-smoke-test` job in
   `.github/workflows/ci.yml` that brings up infra + services and runs a
   planning scenario + cost endpoint validation.
5. **Promote `helper_test_cost_endpoints.sh` to pytest** — new
   `tests/integration/test_cost_endpoints.py` with structured class-based tests
   for all cost-service endpoints.

---

## Files created

| File                                            | Purpose                                      |
| ----------------------------------------------- | -------------------------------------------- |
| `services/planning-service/engine/slots.py`     | Slot allocation engine (ILP, FCFS, priority) |
| `services/planning-service/engine/network.py`   | Network resilience & hub dependency          |
| `services/planning-service/routers/slots.py`    | REST endpoints for `/slots/*`                |
| `services/planning-service/routers/network.py`  | REST endpoints for `/network/*`              |
| `tests/integration/test_e2e_smoke.py`           | E2E smoke test for CI                        |
| `tests/integration/test_cost_endpoints.py`      | Pytest integration for cost endpoints        |
| `scripts/helper_test_planning_slots_network.sh` | Manual test script for new endpoints         |

## Files modified

| File                                         | Change                                         |
| -------------------------------------------- | ---------------------------------------------- |
| `services/planning-service/main.py`          | Wire slots + network routers                   |
| `services/planning-service/requirements.txt` | Add `pulp>=2.8.0`                              |
| `docker-compose.yml`                         | Fix \_common volume mount for planning-service |
| `.github/workflows/ci.yml`                   | Add E2E smoke test job + lint cost/planning    |
| `PLAN.md`                                    | Mark all P2 items as [x]                       |
| `ROADMAP_USECASE.md`                         | Mark 2B and 2D as ✅ shipped                   |
| `docs/services/planning-service/SPEC.md`     | Document new endpoints + file structure        |
| `scripts/README.md`                          | Document new helper script                     |

---

## Bugs fixed along the way

1. **docker-compose.yml — planning-service \_common volume override**: The
   `planning-service` section had a `volumes:` key that overrode the
   `x-python-service` anchor's `_common` mount. Added explicit
   `./services/_common:/app/_common:ro` to the service's volumes list.

2. **numpy type serialization in network.py**: Pandas operations produce
   `numpy.float64` and `numpy.bool_` types which FastAPI's JSON encoder cannot
   serialize. Fixed by explicitly casting all values to native Python types
   (`float()`, `int()`, `bool()`, `str()`) before returning from
   `compute_dependency()`, `simulate_disruption()`, and
   `recommend_diversification()`.

3. **CI lint coverage gap**: `cost-service` and `planning-service` were not
   included in the `lint-python` CI job. Added both.

---

## Design decisions

### Slot allocation (2B)

- **PuLP CBC solver** chosen over external solvers (Gurobi, CPLEX) because:
  - Pure Python dependency, no system packages
  - CBC is fast enough for airport-scale problems (< 1000 requests)
  - MIT licensed, no vendor lock-in
- **Hourly granularity** rather than 15-minute slots for simplicity; the ILP
  constrains by hour which matches IATA slot coordination practice.
- **±4 hour displacement limit** hardcoded in ILP to keep the solution space
  manageable and realistic.

### Network resilience (2D)

- **Herfindahl-Hirschman Index** (HHI) chosen as the concentration metric — it's
  the industry standard used by DOJ/EU for merger reviews.
- **US DOJ thresholds** for rating: <0.15 low, 0.15–0.25 moderate, 0.25–0.50
  high, >0.50 very high.
- **Gravity model** for demand estimation: simple and transparent. Calibration
  constant k=50 produces realistic daily passenger counts for a mid-Atlantic hub.
- Uses BTS T-100 reference data (already mounted at `/app/data/bts/`).

### CI smoke test

- Runs after `docker-build` job to avoid rebuilding images.
- Starts only the minimum services needed (neo4j, kafka, cost-service,
  planning-service, sim-orchestrator).
- 60-second timeout on scenario polling — a 1-day, 1-run scenario completes
  in < 3 seconds.

---

## Test results

All endpoints verified locally:

- `POST /slots/allocate` — FCFS, priority, optimised all return correct allocations
- `POST /slots/compare` — strategy comparison shows correct displacement totals
- `GET /network/dependency` — HHI = 0.1025 (low concentration, 9.8 effective airlines)
- `POST /network/disruption` — removing B6 loses 31 deps/day, 6 exclusive routes
- `POST /network/diversify` — recommends JFK, EWR, PHL, BOS, BRU (gravity-ranked)
- Planning scenario engine still completes correctly with all new routers wired
- ruff lint: All checks passed
- TypeScript build: dashboard and api-gateway both compile clean

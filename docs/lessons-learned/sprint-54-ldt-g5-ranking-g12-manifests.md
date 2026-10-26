# Sprint 54 — LDT roadmap continuation: G5 ranking + G12 manifests

**Date:** 2026-10-26
**Scope:** `ROADMAP_REAL_LDT.md` §10 gaps G5 (recommender ranking) and G12 (k8s
manifests). Recorded as execution-log entries A25 and A26.

## Context

The roadmap tracks twelve open gaps (G1–G12). A20–A24 closed transactional/durable
slices of G1/G2/G7. This sprint picked the two gaps that were (a) explicitly named
in the A24 follow-up audit as still-open and (b) **fully validatable in this
environment** without the heavy ML deps or the full live Compose stack:

- **G5** — `recommender.py` still sorted by `confidence_score` alone.
- **G12** — `k8s/services/` had no `cost-service`/`planning-service` manifests.

Gaps deliberately *not* taken this sprint, and why:
- **G1 remainder, G9** — need atomic domain write + receipt + fact boundaries and
  live producer→consumer contract tests; only meaningful with a running broker/DB.
- **G3** — mechanical `_common` rollout across 9 services; low value per unit risk,
  and import breakage is only fully provable against a live stack.
- **G4, G8** — one calibrated effect library and automatic outcome measurement are
  large and interdependent (and G5's ranking weights can't be calibrated until G8).
- **G6** — concrete action handlers (GDP, rebooking) + incidents command channel
  need live owner validation for the adapter path.

## What was done

### A25 — impact × confidence ÷ cost ranking (G5, partial)
- New pure `analysis-service/services/ranking.py`: per-recommendation
  `impact_value` (passenger-minutes saved) and `cost_value` (disruption-minutes),
  both on a common synthetic scale, from `rec.parameters` + `bn.metrics`.
- `priority_score = impact * confidence / cost`; recommender sorts by it.
- Added 3 additive, defaulted fields to the `Recommendation` model and the
  dashboard type.

### A26 — k8s manifests (G12, partial)
- Added `cost-service.yaml` (8008) and `planning-service.yaml` (8009), single
  replica, correct probes/resources; wired into `kustomization.yaml`; added the
  gateway's cost/planning service URLs.

## Lessons learned

1. **Establish the local baseline before touching anything.** The `.venv` shows
   14 unit failures that look alarming but are *entirely* missing optional ML deps
   (`joblib`, `torch`) — CI installs them and gets 1,022 green. Confirming this up
   front meant every later run was read as "1008 → 1013, same 14 dep-fails = no
   regression" instead of chasing phantom breakage. **Always diff the failure set,
   not the pass count.**

2. **Replace misleading tests, don't delete them.** `test_recs_sorted_by_confidence`
   asserted an invariant the new sort no longer guarantees — and it still *passed*
   by luck on its fixture. Renaming it to `test_recs_sorted_by_priority_score` and
   asserting the real new invariant keeps coverage honest. A test that passes for
   the wrong reason is worse than no test.

3. **Mutation-check the sort key separately from the formula.** Two independent
   mutations were needed: collapsing `priority_score` to confidence (catches the
   scoring module) and reverting the sort key (catches the recommender wiring). The
   second only has teeth because the fixture genuinely has confidence-order ≠
   score-order — worth verifying rather than assuming.

4. **Guard the int/bool trap consistently.** `bool` is an `int` subclass, so
   `float(True) == 1.0` silently poisons a passenger count. A9 already established
   rejecting bools in `to_flight_command`; `ranking._num` follows the same rule.
   Keeping such conventions uniform across the service avoids one-off surprises.

5. **`kubectl --dry-run=client` is not offline.** `apply` does a server-side GET
   for the current config, so against a cluster where RBAC denies `get`, it fails
   with `Forbidden` regardless of manifest validity. For true offline validation
   use `kustomize build` (structure) + a schema validator like `kubeconform`
   (absent here) — or compare against known-good siblings. Don't mistake an RBAC
   denial for a broken manifest.

6. **Heuristic ≠ calibrated — say so in the code.** The ranking weights make
   magnitude and cost matter, but they are not measured benefits. The module
   docstring, the model field descriptions, and the roadmap entry all point at G8
   so nobody later reads `impact_value` as a real euro/minute figure. This repo's
   whole credibility rests on not overclaiming; new numbers inherit that burden.

## Validation summary

| Check | Result |
|---|---|
| `.venv` `pytest tests/unit` | 1,013 passed; 14 pre-existing dep-only failures (joblib/torch), unchanged set |
| `test_analysis_ranking.py` (new) | 5 passed |
| Mutation checks (formula + sort key) | both fail as expected, restored green |
| Ruff (changed Python) | clean |
| Dashboard `tsc -b` / `npm test` | clean / 44 passed |
| `kustomize build k8s/` | OK; cost/planning rendered |

## Still open

G5 (cost-signal unification + calibration), G12 (live cluster apply + load/crash),
and all of G1/G3/G4/G6/G8/G9/G10/G11 remainders. Roadmap stays active.

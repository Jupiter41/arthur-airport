# Lessons Learned: Planning Service Robustness & Cost Models

**Date:** 2025-01-21
**Scope:** planning-service, art-dashboard, Grafana

---

## What was done

1. **Time estimation system** — Backend (`scenarios/metrics.py`) tracks historical
   run durations and estimates future scenario completion times. Exposed via
   `GET /estimate` endpoint and returned in scenario creation responses.

2. **Live progress tracking** — Frontend `ScenarioListItem` component polls
   `GET /scenarios/{id}/status` every 3s for running scenarios, showing a progress
   bar with remaining time estimate.

3. **React state fix** — Replaced inline `if (!selectedId) setSelectedId(...)` with
   `useEffect` in both `ResultsComparison` and `InvestmentDashboard`. The inline
   pattern caused React renders-during-render warnings and sometimes failed to
   trigger re-fetches.

4. **Grafana dashboard** — `infra/grafana/dashboards/planning-service.json` monitors
   active scenarios, completion/failure rates, duration percentiles, MC throughput,
   and template usage breakdown.

5. **QUICKSTART_PLANNING.md** — Added a full worked example with actual API request/
   response samples, interpretation guidance, and new endpoints (service-status,
   estimate).

## Key findings

- The "API disconnected" error was **not** a real backend issue. The dashboard's
  global `useConnectionStore` sets `apiConnected=false` on ANY failed fetch,
  including unrelated services. One flaky service can make the entire dashboard
  appear disconnected.

- The "nothing happens when clicking" on completed scenarios was caused by
  setting React state during render (not in a useEffect). This is a common
  React anti-pattern that sometimes silently fails.

- PowerShell's `curl` is an alias for `Invoke-WebRequest`, not real curl.
  Always use `Invoke-RestMethod` or `bash -c "curl ..."` in PowerShell terminals.

## Files changed

| File | Change |
|---|---|
| `services/planning-service/scenarios/metrics.py` | New — Prometheus metrics + timing estimation |
| `services/planning-service/main.py` | Added `/service-status` endpoint |
| `services/planning-service/routers/planning.py` | Added `/estimate`, time estimates in all responses |
| `services/planning-service/scenarios/runner.py` | Integrated metrics recording |
| `dashboards/art-dashboard/src/hooks/useApi.ts` | Added `estimateDuration()`, `serviceStatus()` |
| `dashboards/art-dashboard/src/pages/Planning/PlanningPage.tsx` | TimeEstimateBar, ScenarioListItem with progress, useEffect fixes |
| `infra/grafana/dashboards/planning-service.json` | New — Grafana dashboard |
| `QUICKSTART_PLANNING.md` | Worked example with API responses |

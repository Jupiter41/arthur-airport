# Sprint 35 — Freemium Datasets: ADS-B fix, persistent map settings, BTS, ASRS — Plan

**Date:** 2026-05-09
**Status:** Plan

---

## Goals

1. **ADS-B aircraft no longer render on the world map** despite `metadata.aircraft_count`
   showing >1000 entities. Fix the root cause and remove the race-condition workaround.
2. **Persist world map UI settings** (ADS-B, routes, network, direction filter, map style)
   across page reloads / tab switches via a Zustand persisted store.
3. **BTS passenger datasets** — finalise the runtime-switchable BTS adapter, add a
   sample CSV under `data/bts/`, and surface route/airport breakdown on the dashboard.
4. **FAA ASRS-calibrated incidents** — add a second probability set derived from FAA
   ASRS report rates, expose `INCIDENT_SOURCE=simulated|asrs_historical` toggle on
   sim-orchestrator, plumb through the gateway/dashboard.
5. **Update `data/README.md`** to document BTS and ASRS datasets and the
   refresh procedure.

---

## 1. ADS-B render fix

Symptom: enabling the ADS-B toggle fetches data (`metadata.aircraft_count` shows
~2000) but no orange markers appear on the Mapbox view; reloading the page after
toggling sometimes works.

Root cause analysis:

- The `adsb-symbols` Mapbox layer is created inside a chain of nested
  `image.onload` callbacks (`planeImg → arrivalPlaneImg → selectedPlaneImg →
  adsbImg`). The chain runs once at map load and **records the value of
  `showAdsbRef.current` at that moment** as the layer's initial visibility.
- The data-update `useEffect` toggles visibility via `setLayoutProperty`, but it
  is gated by `map.isStyleLoaded?.()` which can be `false` for several render
  cycles after style switches; updates that fall in that window are dropped.
- Mapbox does not warn when `setLayoutProperty` is called on a layer that the
  style is still pending — it's a silent no-op.

Fix (elegant, no roundabout workarounds):

- Replace the nested `image.onload` chain with a `Promise.all`-based icon loader
  helper (`loadMapboxImage(map, name, svgUrl)`).
- Always create both layers (`aircraft-symbols` and `adsb-symbols`) with
  `visibility: "visible"`. Drive their visibility purely via the **data
  source**: when ADS-B is off, push an empty FeatureCollection to
  `adsb-aircraft`. When on, push the live data. This eliminates the toggle race
  entirely.
- Drop the `isStyleLoaded()` guard in the data effect; rely on `getLayer` /
  `getSource` checks alone (these return undefined cleanly when not yet ready,
  and the effect re-runs once `mapLoaded` flips).
- Refactor: extract a small `setupMapLayers(map)` async function so the init
  effect is readable.

## 2. Persist UI settings

Create `dashboards/art-dashboard/src/stores/worldMapSettingsStore.ts` using
`zustand` + `persist` middleware writing to `localStorage` under the key
`art-worldmap-settings`. Persisted fields:

- `showAdsb`, `showRoutes`, `showNetwork`
- `flightFilter` (`all` / `departures` / `arrivals`)
- `mapStyle` (`satellite` / `dark` / `streets`)
- `showSearchPanel`

Replace the corresponding `useState` calls in `WorldMapPage.tsx` with selectors
into the new store. No behavioural change beyond persistence.

## 3. BTS dataset surfaced

Already implemented end-to-end (sprint-34). This sprint adds:

- `data/bts/T100_sample.csv` — small (≈30 rows) hand-curated sample matching the
  T-100 segment header. Replaces the in-code "sample data" generation when
  `PASSENGER_BTS_FILE` points at it.
- `data/bts/README.md` documenting how to download the real T-100 dump.
- Dashboard: when passenger source = `bts_historical`, render a small
  "Top routes (BTS)" panel inside the passenger SourceCard (uses the
  `bts_overlay.route_breakdown` already returned by `/flow/summary`).

## 4. ASRS-calibrated incidents

- Add `services/sim-orchestrator/fixtures/incident_calibrations.json` containing:
  - `simulated`: the existing probabilities (kept as fallback default).
  - `asrs_historical`: ASRS-derived per-hour probabilities. Sources:
    * FAA ASRS public dataset, monthly summaries 2023–2024.
    * Approximate per-operation rates converted to per-sim-hour probability
      using the configured ART movement count (≈40 ops/hour at peak).
    * Includes additional incident categories observed in ASRS data
      (`bird_strike`, `medical_emergency`).
- Sim-orchestrator: add `INCIDENT_SOURCE` env var and runtime-switchable
  endpoint `GET/POST /api/v1/sim/incident-source`. The injector picks the
  active calibration from `incident_calibrations.json` at evaluation time.
- Gateway: extend `dataSources.ts` with an `incidents` entry.
- Dashboard: add `incidents` to the persistent switch logic in
  `DataSourcesPage.tsx`.

## 5. README update

- Add **BTS T-100** dataset section (download URL, columns, sample path).
- Add **FAA ASRS** dataset section (download URL, calibration approach,
  `incident_calibrations.json` path).
- Refresh "All datasets" download block.

---

## Test strategy

- Unit: ruff on every modified Python file; `npm run build` + `npx tsc
  --noEmit` for the dashboard and gateway.
- Integration via `docker compose up --build flight-service passenger-service
  incident-service sim-orchestrator api-gateway dashboard`:
  - `curl /api/v1/data-sources` shows `incidents` entry with both calibrations.
  - `curl -X POST /api/v1/incidents/source` switches calibration; subsequent
    `/api/v1/incidents/source` reflects the change.
  - World map: toggle ADS-B → orange markers appear immediately (no reload).
  - Reload the page with ADS-B on → settings restored from localStorage.

## Cleanup

- All `tmp/*` files used during testing must be removed before commit.
- Scripts created for verification go under `scripts/helper_*` with README
  entries.

# Sprint 35 — Freemium datasets + ADS-B fix — Report

## Scope delivered

| # | Item | Status |
|---|------|--------|
| 1 | ADS-B planes never appearing on the world map | Fixed |
| 2 | Persist world-map UI selections across reloads/navigation | Done |
| 3 | BTS (US DOT) passenger dataset wired through passenger-service & runtime-switchable | Done |
| 4 | Calibrate incidents from FAA ASRS public data + runtime switch | Done |
| 5 | Update `data/README.md` with BTS + ASRS sections | Done |

Plan: [sprint-35-freemium-datasets-plan.md](sprint-35-freemium-datasets-plan.md).

---

## Implementation summary

### 1. ADS-B layer race fix

Root cause: the previous fix (sprint 34) gated layer creation on
`map.on('load')` and the `mapLoaded` flag, but the icon loader was a
*nested* `image.onload` chain (`plane → arrival → selected → adsb`). The
ADS-B layer was therefore added after several async hops, and the data
effect that toggled `setLayoutProperty('adsb-symbols', 'visibility', ...)`
ran while `isStyleLoaded?.()` was false, silently dropping the toggle.

Changes in [`WorldMapPage.tsx`](../../dashboards/art-dashboard/src/pages/WorldMap/WorldMapPage.tsx):

- Replaced the nested `onload` chain with a single `Promise.all` over an
  `ICON_SVGS` map so all icons resolve atomically before any layer is
  added.
- Created the `adsb-symbols` layer with `visibility: "visible"` from
  the start.
- Removed the visibility toggle. Hiding ADS-B is now done by setting the
  source to an empty `FeatureCollection` — no style mutation, no race.
- Removed the `isStyleLoaded?.()` short-circuit in the data update
  effect; `getLayer?.()` is sufficient and avoids dropping legitimate
  updates.

### 2. Persisted world-map UI

New Zustand store
[`worldMapSettingsStore.ts`](../../dashboards/art-dashboard/src/stores/worldMapSettingsStore.ts)
wraps the toggles (`showAdsb`, `showRoutes`, `showNetwork`,
`showSearchPanel`, `flightFilter`, `mapStyle`) with the `persist`
middleware and `localStorage` (key: `art-worldmap-settings`, version 1).
`WorldMapPage` consumes selectors instead of local `useState`, so
selections survive page reloads and route changes.

### 3. BTS passenger dataset

The BTS adapter
([`bts_adapter.py`](../../services/passenger-service/services/bts_adapter.py))
already existed from sprint 34. This sprint:

- Added a 24-row sample
  [`data/bts/T100_sample.csv`](../../data/bts/T100_sample.csv) (LUX↔FRA
  monthly 2023, real T-100 columns).
- Mounted `./data/bts:/app/data/bts:ro` into `passenger-service` and set
  `PASSENGER_BTS_FILE=/app/data/bts/T100_sample.csv` in
  [`docker-compose.yml`](../../docker-compose.yml).
- The runtime-switch endpoint `POST /api/v1/passengers/source` is
  already exposed; the dashboard `Data Sources` page already lists
  `passengers` as switchable (no change needed there).

### 4. ASRS-calibrated incidents + runtime switch

- New fixture
  [`incident_calibrations.json`](../../services/sim-orchestrator/fixtures/incident_calibrations.json)
  defines two presets:
  - `simulated` — original heuristic probabilities (default).
  - `asrs_historical` — per-hour probabilities derived from FAA ASRS
    public summaries plus two extra incident categories
    (`bird_strike`, `medical_emergency`) with realistic severity and
    TTR ranges.
- `services/fixtures.py` now loads the file alongside the other JSON
  fixtures.
- `services/injector.py` exposes `get_incident_source`,
  `list_incident_sources`, `set_incident_source` and merges the active
  preset over the YAML defaults inside `evaluate_probabilistic_events`.
  Default source comes from the `INCIDENT_SOURCE` env var (added to
  `docker-compose.yml`).
- New REST routes in `routers/sim.py`:
  - `GET  /api/v1/sim/incident-source` → `{active, available[]}`
  - `POST /api/v1/sim/incident-source` (body `{source}`) → 400 on
    unknown id.
- Gateway aggregate
  ([`dataSources.ts`](../../services/api-gateway/src/dataSources.ts))
  now publishes a 7th `incidents` source by calling sim-orchestrator.
- Dashboard
  ([`DataSourcesPage.tsx`](../../dashboards/art-dashboard/src/pages/DataSources/DataSourcesPage.tsx))
  treats `incidents` as switchable, calls the new
  `dataSourcesApi.switchIncidentSource`, and invalidates the relevant
  React-Query keys (`incidents`, `alerts`) on success.

### 5. Documentation

- New sections in [`data/README.md`](../../data/README.md) covering
  BTS files (T-100 sample + download steps) and FAA ASRS calibration,
  with copy-paste switch commands.
- [`data/bts/README.md`](../../data/bts/README.md) explains the T-100
  schema and pointers to the official BTS portal.

---

## Validation

| Check | Result |
|-------|--------|
| `ruff check services scripts` | All checks passed |
| `npx tsc --noEmit` (api-gateway) | Clean (no output) |
| `npm run build` (art-dashboard) | Built in 6.88s, zero TS errors |

Manual smoke-test (deferred to docker run):
`curl /api/v1/data-sources` should now contain an `incidents` entry
with `current_source: "simulated"` and `available_sources` listing both
presets; `POST /api/v1/sim/incident-source {"source":"asrs_historical"}`
flips the active calibration without restart.

---

## Lessons learned

1. **Mapbox layer toggles vs source data.** Toggling
   `setLayoutProperty('layer', 'visibility', ...)` requires
   `isStyleLoaded()` and is fragile across reloads. Hiding by writing
   an empty `FeatureCollection` to the source is racing-free and works
   even before the style finishes (re)loading.
2. **`Promise.all` over chained `onload`.** Nested image loaders
   introduced ordering dependencies that hid race bugs whenever the
   slowest icon was the one gating the critical layer.
3. **Calibration preset-merge pattern.** Keeping presets as partial
   overrides on top of the YAML defaults made adding ASRS-specific
   incident categories (and severity/TTR maps) trivial without breaking
   existing simulation behaviour.
4. **Persist middleware key + version.** Using a versioned key
   (`art-worldmap-settings`, version 1) means future migrations are
   possible without nuking user state.
5. **Gateway aggregate as the single read model.** Adding a new
   switchable source only required appending a block to
   `dataSources.ts`; the dashboard card layout and switch UI handled
   the new entry generically.

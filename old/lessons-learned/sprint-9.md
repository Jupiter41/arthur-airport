# Sprint 9 — Lessons Learned

**Goal:** All Prometheus targets up. Five Grafana dashboards built. At least three alerting rules fire under simulated conditions.

---

## 1. Metric placement

### Update metrics at the point of change, not just on clock ticks

- Initially, all custom Prometheus gauges were updated inside `_on_clock_tick()` handlers. This works for slowly-changing metrics (passenger counts, flight statuses) but misses fast transitions.
- The `conveyor_zone_status` gauge was updated only on each clock tick. When a system failure set a zone offline and the incident resolved within a few ticks, the offline status was never captured by Prometheus. The ConveyorZoneOffline alert never fired.
- Fix: also update the gauge immediately in `_on_incident_created` and `_on_incident_status_changed`. The clock-tick update still runs as a periodic reconciliation, but the event-driven update ensures transient states are visible.
- **Rule of thumb:** if a state change matters for alerting, update the metric at the mutation site, not in a periodic poll.

### Counter vs Gauge selection

- Counters (`_total` suffix) for events that only go up: transitions, detections, injections.
- Gauges for current state: active counts, queue depths, zone status.
- Histograms for latency distributions: tick latency, TTR, turnaround delay.
- The `cascade_depth_max` gauge required a module-level `_max_cascade_depth` variable to track the running maximum, since `prometheus_client` Gauge has no built-in max-tracking.

---

## 2. Label cardinality

### Keep label sets bounded

- Flight status transitions use `from_status` × `to_status` labels. With ~8 statuses, this creates up to 64 time series — acceptable.
- `baggage_in_system` uses a `status` label with 7 values (dropped_off, inducted, screening, sorting, in_hold, loaded, flagged). Fine for a single-instance service.
- Avoided putting `flight_id` or `passenger_id` as labels — that would create unbounded cardinality and crash Prometheus.

### Zone IDs as labels

- Conveyor zones (31 total) and terminals (3) as label values are fine. The total series count stays under a few hundred per metric.

---

## 3. Prometheus scrape configuration

### Neo4j Community Edition has no metrics

- Neo4j Community Edition does not expose a `/metrics` endpoint. The `neo4j` scrape target always shows `health: down`. This is expected and documented. The UpstreamServiceDown alert does not cover this because it watches `gateway_upstream_errors_total`, not scrape health.
- If observability of Neo4j is needed in the future, either switch to Neo4j Enterprise or use the `neo4j-prometheus-exporter` sidecar.

### Scrape interval tradeoffs

- 5-second scrape interval gives near-real-time dashboards but generates significant TSDB volume. For a portfolio project this is fine; production would use 15–30s.
- The 5s evaluation interval for alerts means transient states lasting <5s may not trigger alerts. This affected the ConveyorZoneOffline test (see §1).

---

## 4. Grafana dashboard design

### Provisioning from JSON files

- Grafana auto-loads dashboards from `/etc/grafana/dashboards/` via the provisioning config. No manual import needed.
- The `GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH` env var sets the home dashboard without Grafana API calls.
- Each dashboard uses a stable `uid` (e.g., `art-sim-overview`) so Grafana doesn't create duplicates on restart.

### Panel layout

- Used a 24-column grid. Stat panels at 4–6 columns wide, time series at 12–24 columns. Row heights of 6–8 for stats, 8–10 for charts.
- Value mappings on stat panels convert numeric codes to human-readable text (e.g., weather category 0→CAVOK, 1→VMC, 2→IMC, 3→LIFR).
- Threshold colors use the standard green→yellow→red progression. Weather visibility thresholds at 1500m and 5000m match aviation standards (LIFR/IFR/VFR).

### Datasource reference

- All panels reference `"datasource": {"type": "prometheus", "uid": "prometheus"}`. This matches the provisioned datasource UID. Using `"Prometheus"` as a name reference also works but is less robust.

---

## 5. Alert testing at accelerated sim speed

### Fast TTR resolution defeats alert detection

- At 60x sim speed, a 20-minute TTR resolves in ~20 real seconds. With 5s scrape + 5s evaluation intervals, an alert with `for: 0m` has at most 2–3 evaluation windows to detect the condition.
- For testing `for: 0m` alerts on transient conditions: slow the simulation to 1x before injecting, verify the alert fires, then restore speed.
- The `for: 2m` SimulationPaused alert naturally requires 2+ real minutes regardless of sim speed (sim is paused, so speed is irrelevant).

### Naturally-firing alerts

- Several alerts fire organically during normal simulation without manual injection:
  - **SecurityQueueLong** fires frequently due to passenger volume spikes.
  - **DeepCascadeActive** fires when incident cascades reach depth ≥ 4.
- This validates that the metrics pipeline works end-to-end without test-specific setup.

---

## 6. Service metric instrumentation

### prometheus_fastapi_instrumentator provides HTTP metrics for free

- All Python services use `prometheus_fastapi_instrumentator` which auto-exposes request count, latency histograms, and in-progress counts on `/metrics`. No custom code needed for basic HTTP observability.
- Custom domain metrics (`prometheus_client` Counter/Gauge/Histogram) supplement the auto-instrumented HTTP metrics.

### api-gateway prom-client patterns

- The Node.js gateway uses `prom-client` with a default registry. Custom metrics (request duration histogram, WebSocket gauges, rate limit counter, upstream errors counter) are defined in separate modules.
- Used `client.register.getSingleMetric(name) || new Counter(...)` pattern to avoid duplicate registration errors when modules are re-imported.

---

## 7. What went well

- All 8/9 targets up on first deploy (neo4j expected down).
- Dashboard provisioning worked on first try — no manual Grafana configuration needed.
- The metrics.py file pattern (one file per service defining all metrics) keeps metric definitions organized and importable.
- Alert rules defined in Sprint 0 (alerts.yml) worked without modification.

## 8. What to improve

- Consider adding `recording_rules` for frequently-computed aggregations (e.g., total passengers across all statuses) to reduce query-time computation.
- The gateway-system dashboard could add a panel for Kafka consumer lag if the kafka-exporter provides per-topic lag metrics.
- Integration tests should validate that specific metrics exist and have expected labels, not just that `/metrics` returns 200.

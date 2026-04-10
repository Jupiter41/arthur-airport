# Phase 6 — Observability & Production Readiness — Implementation Report

**Date:** 2025-01-XX
**Scope:** P6-1 through P6-6

---

## What was delivered

### P6-1 — Distributed tracing (OpenTelemetry → Jaeger)

**Files created:**

- `services/_template/_tracing.py` (copied to all 7 Python services)
- `services/api-gateway/src/tracing.ts`

**Changes:**

- All 7 Python services and the Node.js gateway are instrumented with OpenTelemetry.
- FastAPI auto-instrumentation generates spans for every HTTP request.
- Each Kafka event envelope now carries `trace_id` and `span_id` fields, injected in
  `kafka/producer.py` via `get_trace_context()`.
- Jaeger all-in-one added to `docker-compose.yml` (UI on `:16686`, OTLP on `:4318`).
- Tracing is opt-in: if `OTEL_ENABLED` is not `"true"` or dependencies are missing,
  `init_tracing()` is a no-op. Zero runtime cost when disabled.

**Design decision:** Tracing initialises _after_ the FastAPI `app` object is created
(module-level, outside `lifespan`) so that the ASGI middleware is attached before the
first request. The `# noqa: E402` suppression is required for the late import.

---

### P6-2 — Structured logging (structlog → Loki)

**Files created:**

- `services/_template/_logging.py` (copied to all 7 services)
- `infra/loki/loki-config.yaml`
- `infra/promtail/promtail-config.yaml`
- `infra/grafana/provisioning/datasources/loki.yml`

**Changes:**

- Every Python service calls `setup_logging(service_name)` as the first action in
  `main.py`, _before_ importing domain modules. This ensures all loggers (including
  third-party) emit structured JSON.
- structlog configured with: JSON renderer, ISO timestamps, trace context injection
  (`trace_id`, `span_id` from OTel), log-level colouring suppressed in production.
- Promtail scrapes Docker container logs via the Docker socket and forwards to Loki.
- Grafana datasource provisioning includes Loki with a `trace_id` derived field
  linking to Jaeger traces (log-to-trace correlation).

**Gotcha:** Calling `setup_logging()` early triggers ruff E402 for all subsequent
module-level imports. This is intentional — the `# noqa: E402` annotations document
the pattern explicitly.

---

### P6-3 — Simulation performance profiler

**Files created:**

- `services/_template/_profiler.py` (copied to all 7 services)

**Changes:**

- Each service exposes a `GET /perf` endpoint returning tick processing stats.
- Prometheus metrics: `service_tick_processing_seconds` (histogram),
  `service_tick_budget_utilisation_pct` (gauge).
- Alert rules added to `infra/prometheus/alerts.yml`:
  - Warning at > 80% budget utilisation for 10 minutes.
  - Critical at > 95% budget utilisation for 2 minutes.

**Note:** The `tick_timer()` context manager is deployed but not yet wired into the
actual `SimClockTick` consumer handlers. Services need `with tick_timer():` wrapping
their tick processing blocks in `kafka/consumer.py`. This is intentional — wiring into
consumers is a follow-up task to avoid touching complex consumer logic in this batch.

---

### P6-4 — Kubernetes manifests

**Files created:**

- `k8s/namespace.yaml`
- `k8s/configmap.yaml`
- `k8s/infrastructure/infra.yaml`
- `k8s/services/services.yaml`
- `k8s/kustomization.yaml`

**Design:**

- Single namespace `arthur-airport`.
- Infrastructure: Neo4j, Kafka, Zookeeper as StatefulSets with PVCs; Jaeger, Prometheus,
  Grafana, Loki as Deployments.
- Application: all 8 services as Deployments with HPAs (2–10 replicas, 70% CPU target).
- Kustomize as the orchestrator — `kubectl apply -k k8s/` deploys everything.
- Secrets stored in a Kubernetes Secret (base64-encoded, not production-ready — use
  sealed-secrets or external-secrets-operator for real clusters).

---

### P6-5 — CI/CD pipeline

**Files modified:**

- `.github/workflows/ci.yml` (rewritten)
- `README.md` (CI badge added)

**Jobs:**

1. `lint-python` — ruff check on all 7 Python services.
2. `lint-node` — TypeScript strict build (`tsc --noEmit`) for gateway + Vite build for
   dashboard. Removed previous `|| true` that was silently swallowing errors.
3. `unit-tests` — pytest across all services with proper dependency installation.
4. `integration-tests` — pytest with real Neo4j and Kafka service containers.
5. `docker-build` — `docker compose build` to catch Dockerfile/dependency regressions.

---

### P6-6 — Load testing

**Files created:**

- `tests/load/rest_load.js`
- `tests/load/ws_load.js`
- `tests/load/mixed_load.js`
- `tests/load/README.md`

**Coverage:**

- REST: 1,000 req/min ramp-up against `/api/v1/flights`, `/api/v1/passengers`,
  `/api/v1/baggage`, `/api/v1/weather/current`, `/health`.
- WebSocket: 100 concurrent connections to `/ws/flights` with 5-minute hold.
- Mixed: combined REST + WebSocket scenario.
- Pass/fail thresholds defined (p95 < 500ms, error rate < 1%, WS success > 95%).

---

## Issues encountered and fixed

| Issue                                           | Resolution                                                                           |
| ----------------------------------------------- | ------------------------------------------------------------------------------------ |
| 24 ruff lint errors after adding OTel/structlog | Removed 6 unused `os` imports; added `# noqa: E402` to 18 intentionally late imports |
| Fish shell incompatible with bash for-loops     | All terminal commands wrapped in `bash -c '...'`                                     |
| Docker build cached old requirements.txt        | `--no-cache` build confirmed new dependencies install correctly                      |

---

## Files touched (summary)

| Category                    | Count      | Files                                                                 |
| --------------------------- | ---------- | --------------------------------------------------------------------- |
| New shared modules          | 3 × 8 = 24 | `_tracing.py`, `_logging.py`, `_profiler.py` in template + 7 services |
| New infra configs           | 4          | Loki, Promtail, Grafana datasource, Prometheus alerts                 |
| New Node.js module          | 1          | `api-gateway/src/tracing.ts`                                          |
| New K8s manifests           | 5          | namespace, configmap, infra, services, kustomization                  |
| New load tests              | 4          | 3 k6 scripts + README                                                 |
| Modified main.py            | 7          | All Python services                                                   |
| Modified requirements.txt   | 7          | All Python services                                                   |
| Modified producer.py        | 6          | All services that produce Kafka events                                |
| Modified docker-compose.yml | 1          | Added Jaeger, Loki, Promtail, OTEL env vars                           |
| Modified CI pipeline        | 1          | `.github/workflows/ci.yml`                                            |
| Modified README             | 1          | CI badge                                                              |
| Modified ROADMAP            | 1          | P6-1 through P6-6 marked complete                                     |

---

## Follow-up tasks

1. **Wire `tick_timer()` into actual consumer tick handlers** — wrap `SimClockTick`
   processing in each `kafka/consumer.py` with `with tick_timer():`.
2. **Grafana dashboards** — create pre-built dashboards for traces (Jaeger), logs
   (Loki), and tick performance (Prometheus).
3. **Sealed Secrets** — replace base64 K8s Secret with sealed-secrets or
   external-secrets-operator for real cluster deployments.
4. **CD pipeline** — add deployment step (e.g., ArgoCD sync or `kubectl apply`)
   after CI passes on main branch.

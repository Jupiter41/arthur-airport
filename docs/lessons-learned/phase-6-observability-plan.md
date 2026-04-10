# Phase 6 — Observability & Performance — Implementation Plan

## Scope

Six items (P6-1 through P6-6): distributed tracing, structured logging, performance
profiler, Kubernetes manifests, CI/CD improvements, and load testing.

---

## P6-1 — OpenTelemetry distributed tracing (Jaeger)

**Goal:** End-to-end traces from SimClockTick through all downstream service effects.

### Approach

1. Add `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp`,
   `opentelemetry-instrumentation-fastapi`, `opentelemetry-instrumentation-logging`
   to all Python service `requirements.txt`.
2. Create a shared `_tracing.py` module (copied to each service) that:
   - Initialises a TracerProvider with OTLP exporter
   - Instruments FastAPI via `FastAPIInstrumentor`
   - Reads `OTEL_SERVICE_NAME` and `OTEL_EXPORTER_OTLP_ENDPOINT` from env
3. Add `trace_id` field to every Kafka event envelope. The producer extracts
   current span context and serialises it; the consumer re-injects it.
4. For the Node.js gateway: add `@opentelemetry/sdk-node`,
   `@opentelemetry/auto-instrumentations-node`, `@opentelemetry/exporter-trace-otlp-http`.
   Create `src/tracing.ts` loaded via `--require` before `index.ts`.
5. Add Jaeger (all-in-one) to `docker-compose.yml` on port 16686 (UI) and
   4318 (OTLP HTTP receiver).
6. All services get `OTEL_EXPORTER_OTLP_ENDPOINT: http://jaeger:4318` env var.

### Files touched

- All 7 Python services: `requirements.txt`, `main.py`, new `_tracing.py`
- All 7 Python services: `kafka/producer.py` (add trace_id to envelope)
- `services/api-gateway/package.json`, new `src/tracing.ts`, `Dockerfile`
- `docker-compose.yml` (new jaeger service)

---

## P6-2 — Structured logging with Loki

**Goal:** JSON structured logs shipped to Grafana Loki for log-to-trace correlation.

### Approach

1. Add `structlog` to all Python service `requirements.txt`.
2. Create a shared `_logging.py` module that configures structlog with JSON renderer,
   adds `service_name`, `trace_id`, `span_id` to every log line.
3. Replace `logging.basicConfig(...)` in each service's `main.py` with the structlog
   setup.
4. Add Grafana Loki + Promtail to `docker-compose.yml`.
   - Promtail scrapes Docker container logs (JSON format) from `/var/lib/docker/containers`.
   - Loki receives, indexes, and serves logs.
5. Add Loki as a Grafana datasource in provisioning.
6. For the gateway: configure structured JSON logging via pino or similar.

### Files touched

- All 7 Python services: `requirements.txt`, `main.py`, new `_logging.py`
- `docker-compose.yml` (loki + promtail)
- `infra/loki/` (config files)
- `infra/promtail/` (config files)
- `infra/grafana/provisioning/datasources/` (loki datasource)

---

## P6-3 — Simulation performance profiler

**Goal:** Measure real-time processing budget per service per tick.

### Approach

1. In each Python service's Kafka consumer tick handler, measure wall-clock time
   spent processing each `SimClockTick`.
2. Expose as Prometheus histogram: `service_tick_processing_seconds`.
3. Add a `GET /perf` endpoint per service returning recent tick processing stats.
4. Add derived metric: `tick_budget_utilisation_pct` = tick processing time /
   available budget at current speed.
5. Add Prometheus alert: fire when any service exceeds 80% of tick budget for
   10+ minutes.
6. Add a Grafana panel showing per-service tick budget utilisation.

### Files touched

- All 6 Python domain services: `kafka/consumer.py` (timing wrapper)
- All 6 Python domain services: `main.py` (new `/perf` endpoint)
- `infra/prometheus/alerts.yml` (new alert rule)
- `infra/grafana/dashboards/` (new or updated dashboard panel)

---

## P6-4 — Kubernetes manifests

**Goal:** `kubectl apply -f k8s/` deploys the full stack.

### Approach

- Create `k8s/` directory with:
  - `namespace.yaml` — `arthur-airport` namespace
  - Per-service: `deployment.yaml` + `service.yaml`
  - `configmap.yaml` — shared env vars
  - `hpa.yaml` — HorizontalPodAutoscalers for domain services
  - Infrastructure: Neo4j StatefulSet, Kafka/Zookeeper StatefulSets, Prometheus, Grafana, Jaeger, Loki
  - `kustomization.yaml` for easy deployment

### Files created

- `k8s/namespace.yaml`
- `k8s/configmap.yaml`
- `k8s/infrastructure/` (neo4j, kafka, prometheus, grafana, jaeger, loki)
- `k8s/services/` (one folder per service with deployment + service + hpa)
- `k8s/kustomization.yaml`

---

## P6-5 — CI/CD pipeline improvements

**Goal:** Full GitHub Actions pipeline with lint, unit, integration, build, badge.

### Approach

1. Expand existing `.github/workflows/ci.yml`:
   - Add `analysis-service` to Python lint
   - Make Node lint non-tolerant (remove `|| true`)
   - Add integration test job using Docker Compose services (neo4j + kafka)
   - Add dashboard TypeScript build check
   - Add CI badge to README
2. Add a separate integration test workflow if needed.

### Files touched

- `.github/workflows/ci.yml`
- `README.md` (badge)

---

## P6-6 — Load testing

**Goal:** Performance envelope documented with reproducible k6 scripts.

### Approach

1. Create `tests/load/` directory.
2. k6 scripts:
   - `rest_load.js` — 1,000 req/min to REST endpoints via gateway
   - `ws_load.js` — 100 concurrent WebSocket connections
   - `mixed_load.js` — combined scenario
3. Output: summary JSON + k6 cloud-compatible metrics.
4. Document results and performance envelope.

### Files created

- `tests/load/rest_load.js`
- `tests/load/ws_load.js`
- `tests/load/mixed_load.js`
- `tests/load/README.md`

---

## Implementation order

1. P6-1 (tracing) — foundation for P6-2 (trace_id in logs)
2. P6-2 (structured logging) — depends on trace_id from P6-1
3. P6-3 (profiler) — independent, quick win
4. P6-5 (CI/CD) — independent
5. P6-6 (load testing) — independent
6. P6-4 (K8s) — last, benefits from all other changes

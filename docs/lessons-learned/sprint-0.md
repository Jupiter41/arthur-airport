# Sprint 0 — Lessons learned

**Goal:** Stand up the full infrastructure layer. No domain logic — just plumbing.

---

## Issues encountered

### 1. Confluent image tags require full semver

`confluentinc/cp-zookeeper:7.6` doesn't exist on Docker Hub — the tag must be `7.6.0`.
Always use the full `MAJOR.MINOR.PATCH` tag for Confluent images.

### 2. `npm ci` requires a lockfile

The dashboard and api-gateway Dockerfiles used `npm ci`, which fails without a
`package-lock.json`. Changed to `npm install` for initial scaffolding. Once lockfiles are
committed, switch back to `npm ci` for reproducible builds.

### 3. python:3.11-slim doesn't include curl

Docker healthchecks using `curl` fail on `python:3.11-slim`. Every Python service Dockerfile
needs:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
```

### 4. Neo4j Community Edition has no Prometheus metrics endpoint

The spec references a Prometheus scrape target at `neo4j:2004`. Neo4j Community Edition does not
support the `server.metrics.prometheus.enabled` or `metrics.prometheus.enabled` settings — these
are Enterprise-only features. The Prometheus config keeps the target for forward-compatibility but
it will stay "down" until Neo4j Enterprise is used.

### 5. Fish shell is not bash

The dev machine runs `fish` as the default shell. Bash-specific syntax (`declare -A`, `${var%%}`,
`for ... do ... done`) must be wrapped in `bash -c '...'` or run via script files.

---

## What went well

- The `x-python-service` YAML anchor in docker-compose avoids config duplication across 6 services.
- The `_template/` scaffold pattern made it trivial to stamp out all 6 Python services with
  `sed` substitution for port and service name.
- All 15 containers reached healthy/running state on the first successful build.
- Prometheus scraped 8/9 targets immediately — only neo4j failed (expected, see above).

---

## Final state

| Check                              | Result                                  |
| ---------------------------------- | --------------------------------------- |
| `docker compose ps`                | 15 containers running, all healthy      |
| Neo4j (`:7474`)                    | v5.26 responding                        |
| Kafka broker API                   | Lists API versions                      |
| Health endpoints (8001–8006, 3000) | All `{"status":"ok"}`                   |
| Prometheus targets                 | 8/9 up (neo4j down — Community Edition) |
| Grafana (`:3001`)                  | `database: ok`                          |
| Dashboard (`:5173`)                | HTML page loads                         |

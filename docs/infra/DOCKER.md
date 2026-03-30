# Docker & docker-compose — specification

**Project:** Arthur International Airport Digital Twin  
**Runtime:** Docker ≥ 24 · Docker Compose ≥ 2.20  
**File:** `docker-compose.yml` at repo root

---

## 1. Service inventory

| Service             | Image                             | Port (host)              | Depends on                        |
| ------------------- | --------------------------------- | ------------------------ | --------------------------------- |
| `neo4j`             | `neo4j:5`                         | 7474 (HTTP), 7687 (Bolt) | —                                 |
| `zookeeper`         | `confluentinc/cp-zookeeper:7.6`   | 2181                     | —                                 |
| `kafka`             | `confluentinc/cp-kafka:7.6`       | 9092                     | zookeeper                         |
| `kafka-ui`          | `provectuslabs/kafka-ui:latest`   | 8080                     | kafka                             |
| `kafka-exporter`    | `danielqsj/kafka-exporter:latest` | 9308                     | kafka                             |
| `flight-service`    | `./services/flight-service`       | 8001                     | neo4j, kafka                      |
| `passenger-service` | `./services/passenger-service`    | 8002                     | neo4j, kafka                      |
| `baggage-service`   | `./services/baggage-service`      | 8003                     | neo4j, kafka                      |
| `weather-service`   | `./services/weather-service`      | 8004                     | neo4j, kafka                      |
| `incident-service`  | `./services/incident-service`     | 8005                     | neo4j, kafka                      |
| `sim-orchestrator`  | `./services/sim-orchestrator`     | 8006                     | neo4j, kafka, all domain services |
| `api-gateway`       | `./services/api-gateway`          | 3000                     | kafka, all domain services        |
| `dashboard`         | `./dashboards/art-dashboard`      | 5173                     | api-gateway                       |
| `prometheus`        | `prom/prometheus:v2.51`           | 9090                     | all services                      |
| `grafana`           | `grafana/grafana:10.4`            | 3001                     | prometheus                        |

---

## 2. Full docker-compose.yml

```yaml
name: arthur-airport

x-python-service: &python-service
  restart: unless-stopped
  networks:
    - art-net
  environment:
    NEO4J_URI: bolt://neo4j:7687
    NEO4J_USER: neo4j
    NEO4J_PASSWORD: art-digital-twin
    KAFKA_BROKERS: kafka:9092
    LOG_LEVEL: INFO

services:
  # ─── Infrastructure ────────────────────────────────────────────

  neo4j:
    image: neo4j:5
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      NEO4J_AUTH: neo4j/art-digital-twin
      NEO4J_PLUGINS: '["apoc"]'
      NEO4J_dbms_memory_heap_initial__size: 512m
      NEO4J_dbms_memory_heap_max__size: 1G
    volumes:
      - neo4j-data:/data
      - neo4j-logs:/logs
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://localhost:7474"]
      interval: 10s
      timeout: 5s
      retries: 10

  zookeeper:
    image: confluentinc/cp-zookeeper:7.6
    restart: unless-stopped
    networks: [art-net]
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181
      ZOOKEEPER_TICK_TIME: 2000
    volumes:
      - zookeeper-data:/var/lib/zookeeper/data
      - zookeeper-logs:/var/lib/zookeeper/log

  kafka:
    image: confluentinc/cp-kafka:7.6
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
      KAFKA_AUTO_CREATE_TOPICS_ENABLE: "true"
      KAFKA_LOG_RETENTION_HOURS: 168
    volumes:
      - kafka-data:/var/lib/kafka/data
    healthcheck:
      test:
        [
          "CMD",
          "kafka-broker-api-versions",
          "--bootstrap-server",
          "localhost:9092",
        ]
      interval: 10s
      timeout: 10s
      retries: 10

  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "8080:8080"
    depends_on:
      kafka:
        condition: service_healthy
    environment:
      KAFKA_CLUSTERS_0_NAME: art-cluster
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: kafka:9092

  kafka-exporter:
    image: danielqsj/kafka-exporter:latest
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "9308:9308"
    depends_on:
      kafka:
        condition: service_healthy
    command: ["--kafka.server=kafka:9092"]

  # ─── Domain services ───────────────────────────────────────────

  flight-service:
    <<: *python-service
    build: ./services/flight-service
    ports:
      - "8001:8001"
    depends_on:
      neo4j:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  passenger-service:
    <<: *python-service
    build: ./services/passenger-service
    ports:
      - "8002:8002"
    depends_on:
      neo4j:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8002/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  baggage-service:
    <<: *python-service
    build: ./services/baggage-service
    ports:
      - "8003:8003"
    depends_on:
      neo4j:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8003/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  weather-service:
    <<: *python-service
    build: ./services/weather-service
    ports:
      - "8004:8004"
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: art-digital-twin
      KAFKA_BROKERS: kafka:9092
      INITIAL_WEATHER_CATEGORY: CAVOK
      METAR_INTERVAL_SIM_MINUTES: 30
    depends_on:
      neo4j:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8004/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  incident-service:
    <<: *python-service
    build: ./services/incident-service
    ports:
      - "8005:8005"
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: art-digital-twin
      KAFKA_BROKERS: kafka:9092
      CASCADE_MAX_DEPTH: 5
      PROB_RUNWAY_INCURSION_PER_HR: 0.005
      PROB_BAGGAGE_FIRE_PER_HR: 0.008
      PROB_SECURITY_BREACH_PER_HR: 0.010
      PROB_SYSTEM_FAILURE_PER_HR: 0.015
    depends_on:
      neo4j:
        condition: service_healthy
      kafka:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8005/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  sim-orchestrator:
    <<: *python-service
    build: ./services/sim-orchestrator
    ports:
      - "8006:8006"
    environment:
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: neo4j
      NEO4J_PASSWORD: art-digital-twin
      KAFKA_BROKERS: kafka:9092
      SIM_SPEED_MULTIPLIER: 60
      SIM_START_TIME: "2024-06-15T06:00:00Z"
      DAILY_FLIGHT_TARGET: 420
      DAILY_LOAD_FACTOR_MEAN: 0.80
    depends_on:
      flight-service:
        condition: service_healthy
      passenger-service:
        condition: service_healthy
      baggage-service:
        condition: service_healthy
      weather-service:
        condition: service_healthy
      incident-service:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8006/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  api-gateway:
    build: ./services/api-gateway
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "3000:3000"
    environment:
      PORT: 3000
      JWT_SECRET: art-digital-twin-dev
      KAFKA_BROKERS: kafka:9092
      KAFKA_GROUP_ID: api-gateway
      FLIGHT_SERVICE_URL: http://flight-service:8001
      PASSENGER_SERVICE_URL: http://passenger-service:8002
      BAGGAGE_SERVICE_URL: http://baggage-service:8003
      WEATHER_SERVICE_URL: http://weather-service:8004
      INCIDENT_SERVICE_URL: http://incident-service:8005
      SIM_ORCHESTRATOR_URL: http://sim-orchestrator:8006
      NODE_ENV: development
    depends_on:
      kafka:
        condition: service_healthy
      sim-orchestrator:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 10s
      timeout: 5s
      retries: 5

  dashboard:
    build: ./dashboards/art-dashboard
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "5173:5173"
    environment:
      VITE_API_BASE_URL: http://localhost:3000
      VITE_WS_URL: ws://localhost:3000/ws
    depends_on:
      api-gateway:
        condition: service_healthy

  # ─── Observability ─────────────────────────────────────────────

  prometheus:
    image: prom/prometheus:v2.51.0
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "9090:9090"
    volumes:
      - ./infra/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./infra/prometheus/alerts.yml:/etc/prometheus/alerts.yml:ro
      - prometheus-data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.retention.time=7d"
    depends_on:
      - flight-service
      - passenger-service
      - baggage-service
      - weather-service
      - incident-service
      - sim-orchestrator
      - api-gateway

  grafana:
    image: grafana/grafana:10.4.0
    restart: unless-stopped
    networks: [art-net]
    ports:
      - "3001:3000"
    environment:
      GF_SECURITY_ADMIN_USER: admin
      GF_SECURITY_ADMIN_PASSWORD: art-grafana
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /etc/grafana/dashboards/sim-overview.json
    volumes:
      - ./infra/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./infra/grafana/dashboards:/etc/grafana/dashboards:ro
      - grafana-data:/var/lib/grafana
    depends_on:
      - prometheus

# ─── Networks & volumes ──────────────────────────────────────────

networks:
  art-net:
    driver: bridge

volumes:
  neo4j-data:
  neo4j-logs:
  zookeeper-data:
  zookeeper-logs:
  kafka-data:
  prometheus-data:
  grafana-data:
```

---

## 3. Infra file layout

The `docker-compose.yml` references config files that must exist at these paths:

```
infra/
├── prometheus/
│   ├── prometheus.yml        ← scrape config (see MONITORING.md §2)
│   └── alerts.yml            ← alerting rules (see MONITORING.md §4)
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   └── prometheus.yml
    │   └── dashboards/
    │       └── dashboards.yml
    └── dashboards/
        ├── sim-overview.json
        ├── flights.json
        ├── pax-bag.json
        ├── weather-incidents.json
        └── gateway.json
```

---

## 4. Python service Dockerfile template

All six Python services use the same Dockerfile structure:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001
# Port varies per service — set at build time or override in compose

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://localhost:${PORT:-8001}/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

---

## 5. Node.js gateway Dockerfile template

```dockerfile
FROM node:20-slim

WORKDIR /app

COPY package*.json .
RUN npm ci --only=production

COPY . .

EXPOSE 3000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 \
  CMD curl -f http://localhost:3000/health || exit 1

CMD ["node", "src/index.js"]
```

---

## 6. React dashboard Dockerfile template

```dockerfile
FROM node:20-slim AS builder

WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY infra/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 5173
CMD ["nginx", "-g", "daemon off;"]
```

---

## 7. Useful commands

```bash
# Start everything
docker compose up --build

# Start only infrastructure (Neo4j + Kafka)
docker compose up neo4j zookeeper kafka kafka-ui

# Tail logs for a specific service
docker compose logs -f flight-service

# Restart a single service after code change
docker compose up --build --no-deps flight-service

# Full reset (wipe all volumes = fresh simulation)
docker compose down -v
docker compose up --build

# Run Neo4j Cypher shell
docker compose exec neo4j cypher-shell -u neo4j -p art-digital-twin

# List Kafka topics
docker compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Consume a topic live
docker compose exec kafka kafka-console-consumer \
  --bootstrap-server localhost:9092 \
  --topic flights.events \
  --from-beginning

# Manually inject an incident via curl
curl -X POST http://localhost:3000/api/v1/incidents/inject \
  -H "Authorization: Bearer $(curl -s -X POST http://localhost:3000/auth/token \
    -H 'Content-Type: application/json' \
    -d '{"client_id":"dashboard","secret":"art-dev-secret"}' | jq -r .token)" \
  -H "Content-Type: application/json" \
  -d '{"type":"runway_incursion","severity":"critical","location":"runway-09L"}'
```

---

## 8. Startup time expectations

On a modern laptop with Docker Desktop (cold start, all images pulled):

| Phase                   | Approx. time                      |
| ----------------------- | --------------------------------- |
| Neo4j ready             | 20–35s                            |
| Kafka ready             | 15–25s                            |
| Domain services ready   | 8–12s each (after Neo4j + Kafka)  |
| Sim-orchestrator seed   | 5–10s (after all domain services) |
| Total to first sim tick | ~60–90s                           |

Subsequent starts (images cached, volumes preserved) are ~20–30s total.

---

## 9. Airport configuration system

The simulation is **config-driven**: airport properties are read from `config/airport.yaml` at startup. This allows you to customize the airport without rebuilding code.

### Config file location

The `docker-compose.yml` mounts the local `config/` directory into all services:

```yaml
sim-orchestrator:
  volumes:
    - ./config:/app/config # Mounts config/airport.yaml into container
```

### Config loading order (sim-orchestrator)

1. Check `AIRPORT_CONFIG_PATH` environment variable
2. Try `config/airport.yaml` in repo root (local dev)
3. Try `/app/config/airport.yaml` in container
4. Fall back to built-in defaults (zero downtime)

### Customizing the airport

**Before running docker compose:**

1. Edit `config/airport.yaml`:

   ```yaml
   identity:
     name: "Your Airport"
     iata: "ABC"
     icao: "WXYZ"
     timezone: "Your/Timezone"
   ```

2. Validate your config:
   ```bash
   python scripts/helper_validate_airport_config.py --path config/airport.yaml
   ```

**Then run:**

```bash
docker compose up --build
```

### Environment variable overrides

Simulation defaults can be overridden via env vars on `sim-orchestrator` (takes precedence over config):

| Variable                 | Example                | Notes                                      |
| ------------------------ | ---------------------- | ------------------------------------------ |
| `AIRPORT_CONFIG_PATH`    | `/custom/airport.yaml` | Absolute path to custom config file        |
| `DAILY_FLIGHT_TARGET`    | `1000`                 | Overrides `simulation.daily_flight_target` |
| `DAILY_LOAD_FACTOR_MEAN` | `0.85`                 | Overrides `simulation.load_factor_mean`    |

Example override in docker-compose.yml:

```yaml
sim-orchestrator:
  environment:
    DAILY_FLIGHT_TARGET: 1000 # Override config value
```

### Full configuration reference

See **[HOW_TO_CREATE_AIRPORT.md](../../HOW_TO_CREATE_AIRPORT.md)** for the complete airport configuration schema, validation constraints, and examples.

---

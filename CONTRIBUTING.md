# Contributing

Arthur Airport is a portfolio and teaching project. Issues, questions, and pull requests are welcome.

---

## Running locally

See [README.md](README.md) → Quickstart section. You need Docker ≥ 24 and Docker Compose ≥ 2.20. Everything else runs inside containers.

```bash
git clone https://github.com/YOUR_USERNAME/arthur-airport.git
cd arthur-airport
docker compose up --build
```

The simulation starts automatically. Open http://localhost:5173 for the dashboard.

---

## Project structure

```
docs/
├── architecture/   System design, data model, Kafka schemas, simulation engine
├── services/       One SPEC.md per microservice
├── dashboards/     One spec per React dashboard
└── infra/          Prometheus/Grafana config, Docker compose spec
services/           Microservice implementations (Python/FastAPI + Node.js)
dashboards/         React + TypeScript frontend
infra/              Prometheus, Grafana, and Nginx config files
```

---

## Adding a new service

1. Add a spec in `docs/services/your-service/SPEC.md` following the pattern of existing specs
2. Implement the service in `services/your-service/`
3. Add it to `docker-compose.yml` following the `x-python-service` anchor pattern
4. Register any new Kafka topics in `docs/architecture/EVENT_BUS.md`
5. Add a Prometheus scrape target in `infra/prometheus/prometheus.yml`

## Adding a new dashboard

1. Add a spec in `docs/dashboards/YOUR_DASHBOARD.md`
2. Implement the React page in `dashboards/art-dashboard/src/pages/`
3. Register the route in the app router
4. Add relevant WebSocket subscriptions on mount

---

## Coding conventions

**Python services**
- FastAPI with async handlers throughout
- Pydantic models for all request/response bodies
- `confluent-kafka` for Kafka producer/consumer
- `neo4j` driver for graph queries
- All endpoints documented with FastAPI's built-in OpenAPI support

**Node.js gateway**
- TypeScript strict mode
- `ws` library for WebSocket server
- `kafkajs` for Kafka consumer
- No business logic in the gateway — it is a thin proxy + fan-out layer

**React dashboard**
- TypeScript strict mode
- Zustand for global state
- React Query for REST calls
- Native WebSocket API (no library wrapper)
- Tailwind CSS for styling

---

## Simulated data only

This project contains no real airport, airline, passenger, or flight data of any kind. All names, flight numbers, registrations, and records are procedurally generated. Do not introduce real data in pull requests.

# Contributing

Arthur Airport is a portfolio and teaching project. Issues, questions, and pull requests are welcome.

This repository is specification-first. Before implementing code, read the relevant architecture/service specs and keep documentation synchronized with behavior changes.

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

## Documentation first workflow

For every feature, fix, or behavior change:

1. Update the authoritative spec first:
   - `docs/architecture/*.md` for cross-service concerns
   - `docs/services/{service}/SPEC.md` for service APIs/behavior
   - `docs/dashboards/*.md` for dashboard contracts
2. Implement code changes.
3. Update all impacted READMEs and contributor docs in the same PR.
4. Add a short entry in [CHANGELOG.md](CHANGELOG.md) for notable work.
5. If the change came from a roadmap/sprint gap, update [ROADMAP.md](ROADMAP.md) status and add a lesson report in `docs/lessons-learned/` when useful.

Core references:

- [README.md](README.md)
- [TIMELINE.md](TIMELINE.md)
- [ROADMAP.md](ROADMAP.md)
- [docs/architecture/OVERVIEW.md](docs/architecture/OVERVIEW.md)
- [docs/architecture/EVENT_BUS.md](docs/architecture/EVENT_BUS.md)
- [docs/architecture/DATA_MODEL.md](docs/architecture/DATA_MODEL.md)

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

## Customizing the airport configuration

The airport is fully configurable via `config/airport.yaml` without touching code. This is useful for:

- **Testing**: Run the system as different real-world airports (LHR, NRT, JFK)
- **Scaling**: Validate behavior with 2 or 20 terminals
- **Teaching**: Demonstrate how changes in infrastructure affect operations
- **Scenarios**: Create test configurations for specific incident scenarios

### Steps

1. **Edit `config/airport.yaml`** with your desired airport profile:

   ```yaml
   identity:
     name: "Your Airport Name"
     iata: "ABC"
     icao: "WXYZ"
     timezone: "America/Your_City"
   infrastructure:
     terminals: 3
     gates_per_terminal: [14, 14, 14]
     runways:
       - id: "09L/27R"
         length_m: 3500
         ils: true
   ```

2. **Validate** before running:

   ```bash
   python scripts/helper_validate_airport_config.py --path config/airport.yaml --json
   ```

3. **Rebuild and run**:
   ```bash
   docker compose down -v
   docker compose up --build
   ```

**Full reference:** [HOW_TO_CREATE_AIRPORT.md](HOW_TO_CREATE_AIRPORT.md)

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

## Data privacy

The simulation is built around synthetic data. A few optional reference datasets (for airport metadata or weather history) may be real-world open data, but they must never include PII or sensitive personal records.

When contributing data-related changes:

- Never commit real passenger data
- Never include API secrets in sample files
- Prefer reproducible public datasets documented in [data/README.md](data/README.md)
- Keep legal/usage notices aligned in [LICENSE.md](LICENSE.md)

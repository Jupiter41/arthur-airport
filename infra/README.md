# infra

Configuration files for the observability stack and reverse proxy.

```
infra/
├── prometheus/
│   ├── prometheus.yml     ← scrape config (all 9 targets)
│   └── alerts.yml         ← alerting rules
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

See full specification in:
- [docs/infra/MONITORING.md](../docs/infra/MONITORING.md) — Prometheus scrape config, metrics catalogue, alerting rules, Grafana dashboard panels
- [docs/infra/DOCKER.md](../docs/infra/DOCKER.md) — Full docker-compose spec and Dockerfile templates

## Access

| Service | URL | Credentials |
|---|---|---|
| Grafana | http://localhost:3001 | admin / art-grafana |
| Prometheus | http://localhost:9090 | — |
| Kafka UI | http://localhost:8080 | — |
| Neo4j Browser | http://localhost:7474 | neo4j / art-digital-twin |

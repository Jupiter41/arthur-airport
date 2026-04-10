# Load Testing — Arthur International Airport

Performance testing scripts using [k6](https://k6.io) to validate the API
gateway performance envelope.

## Prerequisites

Install k6:

```bash
# macOS
brew install k6

# Linux (Debian/Ubuntu)
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg \
  --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" \
  | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update && sudo apt-get install k6

# Docker
docker run --rm -i grafana/k6 run - <tests/load/rest_load.js
```

## Test scripts

| Script          | Description               | Target                              |
| --------------- | ------------------------- | ----------------------------------- |
| `rest_load.js`  | REST API load test        | 1,000+ req/min across key endpoints |
| `ws_load.js`    | WebSocket connection test | 100 concurrent WS connections       |
| `mixed_load.js` | Combined REST + WS        | Realistic dashboard usage pattern   |

## Running

```bash
# Start the full stack first
docker compose up --build

# Wait for all services to be healthy, then:

# REST-only load test
k6 run tests/load/rest_load.js

# WebSocket connection test
k6 run tests/load/ws_load.js

# Mixed load (REST + WS combined)
k6 run tests/load/mixed_load.js

# Custom gateway URL
k6 run tests/load/rest_load.js --env BASE_URL=http://192.168.1.100:3000

# Export results to JSON
k6 run tests/load/rest_load.js --out json=results.json
```

## Performance targets

| Metric                | Target         | Notes                         |
| --------------------- | -------------- | ----------------------------- |
| REST p95 latency      | < 500ms        | All GET endpoints             |
| REST p99 latency      | < 1000ms       | All GET endpoints             |
| Error rate            | < 5%           | Under load                    |
| WebSocket connections | 100 concurrent | Sustained for 2+ min          |
| WS message throughput | > 0            | Messages received during test |

## Interpreting results

k6 outputs summary statistics including:

- **http_req_duration** — overall request latency distribution
- **errors** — percentage of failed requests
- **ws_messages_received** — total WebSocket messages during the test
- Custom metrics per endpoint (flight_latency, passenger_latency, etc.)

If p95 latency exceeds 500ms or error rate exceeds 5%, investigate:

1. Check service `/perf` endpoints for tick budget utilisation
2. Check Grafana dashboards for service-level bottlenecks
3. Review Jaeger traces for slow spans
4. Check Prometheus alerts for resource saturation

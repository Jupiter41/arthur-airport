# Kubernetes Manifests — Arthur International Airport

Kustomize-based Kubernetes manifests for deploying the entire Arthur Airport
digital twin to a Kubernetes cluster.

## Directory structure

```
k8s/
├── kustomization.yaml              # Root — deploys everything
├── namespace.yaml                  # Namespace: arthur-airport
├── base/
│   ├── kustomization.yaml
│   ├── configmap.yaml              # Shared ConfigMap + Secret
│   └── prometheus-config.yaml      # Prometheus scrape config
├── infrastructure/
│   ├── kustomization.yaml
│   ├── neo4j.yaml                  # Neo4j 5 (StatefulSet, 5Gi PVC)
│   ├── zookeeper.yaml              # Zookeeper (StatefulSet, 1Gi PVC)
│   ├── kafka.yaml                  # Kafka (StatefulSet, 5Gi PVC)
│   ├── jaeger.yaml                 # Jaeger all-in-one (OTLP)
│   ├── prometheus.yaml             # Prometheus (scrapes all services)
│   ├── grafana.yaml                # Grafana dashboards
│   └── loki.yaml                   # Loki log aggregation
└── services/
    ├── kustomization.yaml
    ├── flight-service.yaml          # Port 8001
    ├── passenger-service.yaml       # Port 8002
    ├── baggage-service.yaml         # Port 8003
    ├── weather-service.yaml         # Port 8004
    ├── incident-service.yaml        # Port 8005
    ├── sim-orchestrator.yaml        # Port 8006
    ├── analysis-service.yaml        # Port 8007 (ML/AI)
    ├── api-gateway.yaml             # Port 3000 (LoadBalancer)
    └── dashboard.yaml               # Port 5173 (LoadBalancer)
```

## Prerequisites

- A running Kubernetes cluster (minikube, kind, EKS, GKE, AKS, etc.)
- `kubectl` configured to talk to the cluster
- Docker images built and pushed to a registry accessible by the cluster

## Building images

All images follow the naming convention `arthur-airport/{service}:latest`:

```bash
# Build all images
docker compose build

# Tag and push to a registry (example with a private registry)
for svc in flight-service passenger-service baggage-service weather-service \
           incident-service sim-orchestrator analysis-service api-gateway dashboard; do
  docker tag "arthur-airport-${svc}:latest" "your-registry.io/arthur-airport/${svc}:latest"
  docker push "your-registry.io/arthur-airport/${svc}:latest"
done
```

If using minikube, you can load images directly:

```bash
# Point Docker at minikube's daemon
eval $(minikube docker-env)
docker compose build
```

## Deploying

### Deploy everything

```bash
kubectl apply -k k8s/
```

### Deploy only infrastructure (Neo4j + Kafka + observability)

Useful when developing services locally against in-cluster infra:

```bash
kubectl apply -k k8s/base/
kubectl apply -k k8s/infrastructure/
```

### Deploy only application services

Requires infrastructure to be running first:

```bash
kubectl apply -k k8s/services/
```

### Deploy a single service

Each service file is self-contained (Deployment + Service + HPA):

```bash
kubectl apply -f k8s/services/flight-service.yaml -n arthur-airport
```

### Redeploy a single service after code change

```bash
docker compose build flight-service
# If using a registry:
docker push your-registry.io/arthur-airport/flight-service:latest
kubectl rollout restart deployment/flight-service -n arthur-airport
```

## Configuration

### Shared config (all services)

Defined in `base/configmap.yaml`:

| Variable                      | Value                | Description                |
| ----------------------------- | -------------------- | -------------------------- |
| `NEO4J_URI`                   | `bolt://neo4j:7687`  | Neo4j Bolt endpoint        |
| `NEO4J_USER`                  | `neo4j`              | Neo4j username             |
| `KAFKA_BROKERS`               | `kafka:9092`         | Kafka bootstrap servers    |
| `LOG_LEVEL`                   | `INFO`               | Logging level              |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://jaeger:4318` | OpenTelemetry collector    |
| `OTEL_ENABLED`                | `true`               | Enable distributed tracing |

### Secrets

Defined in `base/configmap.yaml` (Secret object):

| Key              | Default                | Description     |
| ---------------- | ---------------------- | --------------- |
| `NEO4J_PASSWORD` | `art-digital-twin`     | Neo4j password  |
| `JWT_SECRET`     | `art-digital-twin-dev` | JWT signing key |

### Analysis service (ML/AI)

The analysis-service has additional env vars for LLM and RL:

| Variable        | Source                                | Description           |
| --------------- | ------------------------------------- | --------------------- |
| `LLM_BASE_URL`  | `llm-secrets` Secret (optional)       | LLM API endpoint      |
| `LLM_API_KEY`   | `llm-secrets` Secret (optional)       | LLM API key           |
| `LLM_MODEL`     | Hardcoded `gpt-4o-mini`               | LLM model name        |
| `RL_MODEL_PATH` | Hardcoded `/app/models/rl_policy.zip` | Trained RL model path |

To provide LLM credentials, create the optional secret:

```bash
kubectl create secret generic llm-secrets \
  -n arthur-airport \
  --from-literal=LLM_BASE_URL=https://api.openai.com/v1 \
  --from-literal=LLM_API_KEY=sk-your-key-here
```

### Per-service env vars

Each service has additional environment variables set directly in its
deployment YAML. See the individual files or the service SPEC docs
(`docs/services/{name}/SPEC.md`) for details.

## Resource allocations

| Service           | CPU request/limit | Memory request/limit | HPA          |
| ----------------- | ----------------- | -------------------- | ------------ |
| flight-service    | 100m / 500m       | 256Mi / 512Mi        | 1–3 replicas |
| passenger-service | 150m / 750m       | 384Mi / 768Mi        | 1–3 replicas |
| baggage-service   | 100m / 500m       | 256Mi / 512Mi        | 1–3 replicas |
| weather-service   | 50m / 250m        | 128Mi / 256Mi        | —            |
| incident-service  | 100m / 500m       | 256Mi / 512Mi        | —            |
| sim-orchestrator  | 200m / 1000m      | 384Mi / 768Mi        | —            |
| analysis-service  | 200m / 1000m      | 512Mi / 1Gi          | —            |
| api-gateway       | 100m / 500m       | 256Mi / 512Mi        | 1–5 replicas |
| dashboard         | 50m / 200m        | 64Mi / 128Mi         | —            |

**Total minimum**: ~1.1 CPU, ~2.5Gi memory (services only, excluding infra).

## Exposed services

Two services are exposed via `LoadBalancer`:

| Service     | Port | Purpose              |
| ----------- | ---- | -------------------- |
| api-gateway | 3000 | REST API + WebSocket |
| dashboard   | 5173 | React UI             |

All other services use `ClusterIP` (internal only).

## Monitoring

Once deployed, access:

- **Grafana**: `kubectl port-forward svc/grafana 3001:3000 -n arthur-airport`
  → http://localhost:3001 (admin / art-grafana)
- **Prometheus**: `kubectl port-forward svc/prometheus 9090:9090 -n arthur-airport`
- **Jaeger**: `kubectl port-forward svc/jaeger 16686:16686 -n arthur-airport`
- **Neo4j Browser**: `kubectl port-forward svc/neo4j 7474:7474 -n arthur-airport`

## Troubleshooting

```bash
# Check pod status
kubectl get pods -n arthur-airport

# View logs for a service
kubectl logs -f deployment/flight-service -n arthur-airport

# Describe a failing pod
kubectl describe pod -l app=flight-service -n arthur-airport

# Check HPA status
kubectl get hpa -n arthur-airport

# Verify kustomize output without applying
kubectl kustomize k8s/

# Delete everything and start fresh
kubectl delete namespace arthur-airport
kubectl apply -k k8s/
```

## Differences from docker-compose

| Concern        | docker-compose                                                  | Kubernetes                                                               |
| -------------- | --------------------------------------------------------------- | ------------------------------------------------------------------------ |
| Topic creation | `kafka-init` container + `KAFKA_AUTO_CREATE_TOPICS_ENABLE=true` | Manual topic creation required (`KAFKA_AUTO_CREATE_TOPICS_ENABLE=false`) |
| Secrets        | Plain text in YAML                                              | Kubernetes Secrets (base64-encoded)                                      |
| Health checks  | Docker healthcheck                                              | readinessProbe + livenessProbe                                           |
| Scaling        | Manual `--scale`                                                | HPA with CPU-based autoscaling                                           |
| Networking     | `art-net` bridge                                                | Kubernetes DNS + ClusterIP services                                      |
| Storage        | Docker volumes                                                  | PersistentVolumeClaims                                                   |

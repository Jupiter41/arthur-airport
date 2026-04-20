# Sprint 22 — K8s Refactor + ML Page Completion

## Issues

### 1. K8s structure is monolithic and hard to maintain

- `k8s/infrastructure/infra.yaml` has ~350 lines with Neo4j, Kafka, ZK, Jaeger, Prometheus, Grafana, Loki all in one file
- `k8s/services/services.yaml` has ~500 lines with all 9 services in one file
- Can't deploy a single service independently
- Missing `prometheus-config` ConfigMap (referenced by Prometheus deployment but not defined)
- Analysis service missing LLM/RL env vars that exist in docker-compose

### 2. ML Training page incomplete

- After training, model path (RL_MODEL_PATH) isn't surfaced
- No env config panel showing RL_MODEL_PATH, LLM_BASE_URL etc.
- User can't see/configure training-related environment from the UI
- Need a panel to show config and model deployment status

## Plan

### K8s Refactor

**Target structure:**

```
k8s/
├── README.md                     # Usage documentation
├── kustomization.yaml            # Root kustomization
├── namespace.yaml                # Namespace
├── base/
│   ├── kustomization.yaml
│   ├── configmap.yaml            # Shared ConfigMap + Secret
│   └── prometheus-config.yaml    # Prometheus scrape config
├── infrastructure/
│   ├── kustomization.yaml
│   ├── neo4j.yaml
│   ├── zookeeper.yaml
│   ├── kafka.yaml
│   ├── jaeger.yaml
│   ├── prometheus.yaml
│   ├── grafana.yaml
│   └── loki.yaml
└── services/
    ├── kustomization.yaml
    ├── flight-service.yaml
    ├── passenger-service.yaml
    ├── baggage-service.yaml
    ├── weather-service.yaml
    ├── incident-service.yaml
    ├── sim-orchestrator.yaml
    ├── analysis-service.yaml
    ├── api-gateway.yaml
    └── dashboard.yaml
```

Each service YAML contains its Deployment + Service + HPA (if applicable).
Each subdirectory has its own kustomization.yaml so you can deploy independently:

- `kubectl apply -k k8s/` → everything
- `kubectl apply -k k8s/infrastructure/` → infra only
- `kubectl apply -k k8s/services/` → all services
- `kubectl apply -f k8s/services/flight-service.yaml` → single service

**Fixes:**

- Add missing `prometheus-config` ConfigMap
- Add LLM/RL env vars to analysis-service
- Add proper labels (`app.kubernetes.io/*`)

### ML Page Completion

**Add an Environment Config panel** that shows:

- RL_MODEL_PATH and whether a model is loaded
- LLM_BASE_URL, LLM_MODEL (from existing `/analysis/llm-config`)
- MODELS_PATH directory listing

**Add a new backend endpoint:**

- `GET /api/v1/analysis/training/config` → returns env config for training

**After training completes:**

- Show the output model path clearly
- Show "Model ready — will be loaded on next service restart" or "Model loaded (active)" status

## Status

- [x] K8s split into per-component files
- [x] Add base/ with configmap + prometheus config
- [x] Root kustomization updated
- [x] Analysis service k8s gets LLM/RL env vars
- [x] k8s README
- [x] ML page env config panel
- [x] Backend training config endpoint
- [x] Tests pass (tsc, vite, ruff)

## Results

### K8s Refactor

**Before:** 2 monolithic files (infra.yaml ~350 lines, services.yaml ~500 lines), no sub-kustomizations, missing prometheus-config ConfigMap.

**After:** 20 files across 3 tiers (`base/`, `infrastructure/`, `services/`), each component in its own file, each tier independently deployable via its own kustomization.yaml.

**Resource count (verified via `kubectl kustomize k8s/`):**

- 1 Namespace, 2 ConfigMaps, 1 Secret, 13 Deployments, 3 StatefulSets, 16 Services, 4 HPAs
- **Total: 40 resources, 1303 lines**

**Key improvements:**

- Independent deployment: `kubectl apply -k k8s/infrastructure/` or `kubectl apply -f k8s/services/flight-service.yaml`
- Missing `prometheus-config` ConfigMap now defined
- Analysis service has LLM/RL env vars (LLM secrets via optional `llm-secrets` Secret)
- Proper `app.kubernetes.io/*` labels on all resources
- Resource requests/limits on infra components (were missing)
- Comprehensive README with usage, config, troubleshooting

### ML Page Completion

**New endpoint:** `GET /api/v1/analysis/training/config` — returns RL model status, model files, and env vars.

**New panel:** `EnvironmentConfigPanel` — shows RL agent status (path/exists/loaded), model files, and all training env vars with contextual hints.

### Validation

| Check                    | Result                  |
| ------------------------ | ----------------------- |
| `tsc --noEmit`           | Clean                   |
| `npx vite build`         | 831 modules, 12s        |
| `ruff check services/`   | All passed              |
| `docker compose build`   | All services built      |
| `kubectl kustomize k8s/` | 40 resources, no errors |

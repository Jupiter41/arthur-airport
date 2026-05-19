# Data Source Adapter Refactoring Plan

## Problem
Three services (weather, passenger, incident) each independently implement data source
switching with duplicated patterns:
- Source state tracking
- Adapter lifecycle (load/unload)
- REST endpoints (GET/POST source)
- Gateway aggregation

## Solution: Shared DataSourceRegistry

### New shared module: `services/_common/data_sources.py`

```python
class DataSourceAdapter(Protocol):
    """Interface all data source adapters must implement."""
    @property
    def source_id(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property 
    def is_loaded(self) -> bool: ...
    def load(self) -> int: ...

class DataSourceRegistry:
    """Manages registration, switching, and listing of data sources for a theme."""
    def __init__(self, theme: str, env_var: str, default: str): ...
    def register(self, adapter: DataSourceAdapter): ...
    def switch(self, source_id: str) -> dict: ...
    def get_active(self) -> DataSourceAdapter | None: ...
    @property
    def active_source(self) -> str: ...
    def list_sources(self) -> list[dict]: ...
    def info(self) -> dict: ...
```

### Migration path per service
1. Create adapters implementing the protocol
2. Create registry in consumer state init
3. Wire REST endpoints to registry.info() and registry.switch()
4. No changes to Kafka event production (adapters are at the edge)

### Test plan
- Registry: register/switch/list/info
- Protocol compliance for each adapter
- REST endpoint shape consistency

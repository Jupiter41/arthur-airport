"""conftest.py — Import helpers for service unit tests.

Each service has its own `services/` package. We provide a helper
to cleanly import from a specific service context.
"""

import importlib
import sys
import os
from types import ModuleType

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SERVICE_PATHS = {
    "flight": os.path.join(ROOT, "services", "flight-service"),
    "weather": os.path.join(ROOT, "services", "weather-service"),
    "passenger": os.path.join(ROOT, "services", "passenger-service"),
    "baggage": os.path.join(ROOT, "services", "baggage-service"),
    "incident": os.path.join(ROOT, "services", "incident-service"),
    "sim": os.path.join(ROOT, "services", "sim-orchestrator"),
    "analysis": os.path.join(ROOT, "services", "analysis-service"),
    "cost": os.path.join(ROOT, "services", "cost-service"),
}


def import_service_module(service: str, module_path: str) -> ModuleType:
    """Import a module from a specific service directory.
    
    Clears cached 'services.*' modules to avoid cross-service collisions,
    then imports the target module from the specified service context.
    """
    svc_dir = SERVICE_PATHS[service]
    
    # Remove stale service entries from path
    for p in SERVICE_PATHS.values():
        while p in sys.path:
            sys.path.remove(p)
    
    # Clear cached services package and other per-service modules
    # that can collide between services sharing the same module names
    _CLEAR_PREFIXES = ("services", "db", "kafka", "routers", "metrics")
    for k in list(sys.modules):
        for prefix in _CLEAR_PREFIXES:
            if k == prefix or k.startswith(f"{prefix}."):
                del sys.modules[k]
                break
    
    sys.path.insert(0, svc_dir)
    # Ensure _common package is reachable (shared library at services/_common/)
    common_dir = os.path.join(ROOT, "services")
    if common_dir not in sys.path:
        sys.path.insert(0, common_dir)
    return importlib.import_module(module_path)

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
    
    # Clear cached services package
    for k in list(sys.modules):
        if k == "services" or k.startswith("services."):
            del sys.modules[k]
    
    # Also clear db.* which can collide between services
    for k in list(sys.modules):
        if k == "db" or k.startswith("db."):
            del sys.modules[k]
    
    sys.path.insert(0, svc_dir)
    return importlib.import_module(module_path)

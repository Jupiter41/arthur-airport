"""Common /ready helper for FastAPI services.

Every domain service exposes a ``GET /ready`` probe used by Docker, Kubernetes,
and the dashboard. Before this helper, each service duplicated the same boilerplate
(neo4j check + kafka check + consumer check) with subtly different payload shapes
and HTTP semantics. This module gives them a single contract:

* ``200 OK`` with ``{"status": "ready", <check_name>: True, ...}`` when all checks pass.
* ``503 Service Unavailable`` with ``{"status": "not ready", <check_name>: <bool>, ...}``
  raised as ``HTTPException`` when any check fails or throws.

Each check is a zero-argument callable that returns a ``bool`` or an awaitable bool.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Union

from fastapi import HTTPException

CheckFn = Callable[[], Union[bool, Awaitable[bool]]]


async def evaluate_readiness(checks: dict[str, CheckFn]) -> dict[str, bool]:
    """Run all checks and return ``{name: bool}`` without raising.

    Exceptions raised by a check are swallowed and recorded as ``False``.
    """
    results: dict[str, bool] = {}
    for name, fn in checks.items():
        try:
            value = fn()
            if inspect.isawaitable(value):
                value = await value
            results[name] = bool(value)
        except Exception:  # noqa: BLE001 — readiness must never raise
            results[name] = False
    return results


async def readiness_response(checks: dict[str, CheckFn]) -> dict[str, object]:
    """Evaluate ``checks`` and either return the ready payload or raise 503.

    Use directly in a FastAPI handler::

        @app.get("/ready")
        async def ready():
            return await readiness_response({
                "neo4j": check_neo4j,
                "kafka": check_kafka,
                "consumer": is_consumer_running,
            })
    """
    results = await evaluate_readiness(checks)
    if all(results.values()):
        return {"status": "ready", **results}
    raise HTTPException(
        status_code=503,
        detail={"status": "not ready", **results},
    )

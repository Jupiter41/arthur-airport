"""Optional fuel-price feed for cost-service.

Real airports run their cost models off live jet-fuel benchmarks (Platts,
IATA Jet Fuel Monitor, EIA Spot). This module exposes a tiny shim so the
service can:

* read a static fixture by default (`fuel_price_per_kg_eur` in
  ``cost_rates.json``);
* opportunistically fetch a real value from a public JSON endpoint pointed to
  by the ``FUEL_PRICE_URL`` environment variable;
* refresh that value periodically without ever blocking startup or the hot
  Kafka loop.

The expected JSON shape is intentionally minimal so any provider can be wrapped
behind a tiny static-file proxy::

    {
        "price_eur_per_kg": 0.92,
        "as_of": "2026-06-04T00:00:00Z",
        "source": "EIA US Gulf Coast Spot"
    }

Errors are swallowed and logged at WARNING — the fixture value is kept as the
source of truth so the simulator never stalls on a flaky upstream.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Refresh cadence in wall-clock seconds. 6 h is comfortably more frequent than
# any public weekly benchmark and well below the daily turnover of cost rates.
DEFAULT_REFRESH_S = 6 * 60 * 60


def _coerce_price(payload: Any) -> float | None:
    """Extract a positive float jet-fuel price (EUR/kg) from any reasonable JSON shape."""
    if not isinstance(payload, dict):
        return None
    candidate = (
        payload.get("price_eur_per_kg")
        or payload.get("price")
        or payload.get("value")
    )
    try:
        price = float(candidate)
    except (TypeError, ValueError):
        return None
    if price <= 0 or price > 10:  # sanity guard — jet fuel never trades >€10/kg
        return None
    return price


async def fetch_fuel_price(url: str, *, timeout_s: float = 5.0) -> dict | None:
    """Fetch a single fuel-price snapshot. Returns ``None`` on any failure."""
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:  # network / json / status — all non-fatal
        logger.warning("fuel-price fetch failed", url=url, error=str(exc))
        return None
    price = _coerce_price(payload)
    if price is None:
        logger.warning("fuel-price payload rejected", url=url, payload_keys=list(payload) if isinstance(payload, dict) else None)
        return None
    return {
        "price_eur_per_kg": price,
        "as_of": payload.get("as_of"),
        "source": payload.get("source", url),
    }


def apply_to_rates(rates: dict, snapshot: dict) -> None:
    """Patch the in-memory rates dict with a freshly-fetched price."""
    rates.setdefault("delay_costs", {})["fuel_price_per_kg_eur"] = snapshot["price_eur_per_kg"]
    rates.setdefault("_meta", {})["fuel_price"] = {
        "value_eur_per_kg": snapshot["price_eur_per_kg"],
        "as_of": snapshot.get("as_of"),
        "source": snapshot.get("source"),
    }
    logger.info(
        "fuel-price applied",
        eur_per_kg=snapshot["price_eur_per_kg"],
        source=snapshot.get("source"),
    )


async def refresh_once(rates: dict, *, url: str | None = None) -> bool:
    """Fetch once and patch ``rates`` in place. Returns True on success."""
    url = url or os.getenv("FUEL_PRICE_URL")
    if not url:
        return False
    snapshot = await fetch_fuel_price(url)
    if snapshot is None:
        return False
    apply_to_rates(rates, snapshot)
    return True


async def refresh_loop(rates: dict, *, interval_s: int = DEFAULT_REFRESH_S) -> None:
    """Background task — refreshes ``rates`` every ``interval_s`` seconds.

    No-op (returns immediately) when ``FUEL_PRICE_URL`` is unset so the loop
    never spins idly in tests / local dev.
    """
    if not os.getenv("FUEL_PRICE_URL"):
        logger.info("fuel-price feed disabled (FUEL_PRICE_URL unset)")
        return
    while True:
        await refresh_once(rates)
        await asyncio.sleep(interval_s)

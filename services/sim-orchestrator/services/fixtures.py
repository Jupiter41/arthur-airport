"""Fixture loader — loads JSON seed data from the fixtures directory."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from services.airport_config import load_airport_runtime_config

logger = logging.getLogger(__name__)

_fixtures: dict[str, Any] = {}

FIXTURES_PATH = os.getenv("FIXTURES_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "fixtures"))

FIXTURE_FILES = [
    "airlines",
    "aircraft_types",
    "destinations",
    "first_names",
    "surnames",
    "nationalities",
    "dg_classes",
    "events",
    "layout",
]


def _normalize_terminal_code(raw: str | None, fallback: str) -> str:
    if not raw:
        return fallback
    token = str(raw).strip().upper()
    if token.startswith("T-") and len(token) >= 3:
        token = token[2:]
    if len(token) == 1 and token.isalpha():
        return token
    return fallback


def _apply_airline_overrides(fixtures: dict[str, Any]) -> None:
    runtime = load_airport_runtime_config()
    if not runtime.airlines:
        return

    airlines = fixtures.get("airlines")
    if not isinstance(airlines, list):
        return

    terminal_default = runtime.terminal_codes[0]
    default_fleet = ["A320"]
    for existing in airlines:
        fleet = existing.get("fleet")
        if isinstance(fleet, list) and fleet:
            default_fleet = fleet
            break

    by_code: dict[str, dict[str, Any]] = {
        a.get("code", ""): a
        for a in airlines
        if isinstance(a, dict) and a.get("code")
    }

    for override in runtime.airlines:
        preferred_terminal = _normalize_terminal_code(
            override.hub_terminal,
            terminal_default,
        )
        target = by_code.get(override.code)
        if target is None:
            target = {
                "code": override.code,
                "name": override.name,
                "hub": runtime.identity.iata,
                "market_share": override.market_share,
                "preferred_terminal": preferred_terminal,
                "fleet": list(default_fleet),
            }
            airlines.append(target)
            by_code[override.code] = target
        else:
            target["name"] = override.name
            target["hub"] = runtime.identity.iata
            target["market_share"] = override.market_share
            target["preferred_terminal"] = preferred_terminal
            if not target.get("fleet"):
                target["fleet"] = list(default_fleet)

    total_share = sum(
        float(a.get("market_share", 0.0))
        for a in airlines
        if isinstance(a, dict)
    )
    if total_share > 0:
        for airline in airlines:
            if isinstance(airline, dict):
                airline["market_share"] = float(airline.get("market_share", 0.0)) / total_share


def load_fixtures() -> dict[str, Any]:
    """Load all fixture JSON files into memory. Cached after first call."""
    global _fixtures
    if _fixtures:
        return _fixtures

    base = Path(FIXTURES_PATH)
    for name in FIXTURE_FILES:
        path = base / f"{name}.json"
        with open(path, "r") as f:
            _fixtures[name] = json.load(f)
        logger.info("Loaded fixture: %s (%d items)", name, len(_fixtures[name]) if isinstance(_fixtures[name], list) else len(_fixtures[name].keys()))

    _apply_airline_overrides(_fixtures)

    return _fixtures


def get_fixtures() -> dict[str, Any]:
    """Return loaded fixtures. Raises if not loaded."""
    if not _fixtures:
        raise RuntimeError("Fixtures not loaded — call load_fixtures() first")
    return _fixtures

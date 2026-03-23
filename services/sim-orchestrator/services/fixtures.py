"""Fixture loader — loads JSON seed data from the fixtures directory."""

import json
import logging
import os
from pathlib import Path
from typing import Any

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
]


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

    return _fixtures


def get_fixtures() -> dict[str, Any]:
    """Return loaded fixtures. Raises if not loaded."""
    if not _fixtures:
        raise RuntimeError("Fixtures not loaded — call load_fixtures() first")
    return _fixtures

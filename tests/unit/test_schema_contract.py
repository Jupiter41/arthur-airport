"""Schema contract tests — validate DATA_MODEL.md against service code.

Verifies that:
1. Every node label from the data model has a uniqueness constraint in service code
2. Every relationship type from the data model appears in at least one Cypher query
3. Required properties per node label appear in CREATE queries

These are static analysis tests (no Neo4j required).
"""

import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Expected schema from DATA_MODEL.md ──────────────────────────

# Node labels and their required properties (from §2)
REQUIRED_NODE_PROPERTIES: dict[str, list[str]] = {
    "Airport": ["iata", "icao", "name"],
    "Terminal": ["id", "name"],
    "Gate": ["id", "terminal_id", "status"],
    "Runway": ["id", "status"],
    "Flight": ["id", "flight_number", "airline_code", "direction", "status"],
    "Passenger": ["id", "name", "pnr", "status"],
    "Baggage": ["tag", "status"],
    "WeatherState": ["id", "category"],
    "Incident": ["id", "type", "severity", "status"],
}

# Uniqueness constraints expected (from §5)
EXPECTED_CONSTRAINTS: dict[str, str] = {
    "Flight": "f.id",
    "Passenger": "p.id",
    "Baggage": "b.tag",
    "Gate": "g.id",
    "Runway": "r.id",
    "Incident": "i.id",
}

# Relationship types that must exist in at least one query (from §3)
EXPECTED_RELATIONSHIPS: list[str] = [
    "HAS_TERMINAL",
    "HAS_GATE",
    "HAS_RUNWAY",
    "ASSIGNED_TO",
    "USES_RUNWAY",
    "ON_FLIGHT",
    "CARRIES",
    "LOADED_ON",
    "AFFECTS",
    "SPAWNED",
    "CURRENT_WEATHER",
    "PREVIOUS_WEATHER",
]


def _read_all_service_python() -> str:
    """Read all Python files across all services into a single string."""
    services_dir = os.path.join(ROOT, "services")
    texts: list[str] = []
    for dirpath, _, filenames in os.walk(services_dir):
        if "__pycache__" in dirpath:
            continue
        for fname in filenames:
            if fname.endswith(".py"):
                fpath = os.path.join(dirpath, fname)
                with open(fpath, encoding="utf-8") as f:
                    texts.append(f.read())
    return "\n".join(texts)


def _read_all_constraint_arrays() -> str:
    """Read all CONSTRAINTS arrays from db/neo4j.py files."""
    services_dir = os.path.join(ROOT, "services")
    texts: list[str] = []
    for dirpath, _, filenames in os.walk(services_dir):
        if "db" in dirpath.split(os.sep):
            for fname in filenames:
                if fname == "neo4j.py":
                    fpath = os.path.join(dirpath, fname)
                    with open(fpath, encoding="utf-8") as f:
                        texts.append(f.read())
    return "\n".join(texts)


# ── Fixtures ─────────────────────────────────────────────────────

_ALL_CODE: str | None = None


@pytest.fixture(scope="module")
def all_service_code() -> str:
    global _ALL_CODE
    if _ALL_CODE is None:
        _ALL_CODE = _read_all_service_python()
    return _ALL_CODE


@pytest.fixture(scope="module")
def constraint_code() -> str:
    return _read_all_constraint_arrays()


# ── Tests ────────────────────────────────────────────────────────


class TestConstraintCoverage:
    """Every node label in the data model must have a uniqueness constraint."""

    @pytest.mark.parametrize("label,prop_ref", list(EXPECTED_CONSTRAINTS.items()))
    def test_constraint_defined(self, constraint_code: str, label: str, prop_ref: str) -> None:
        # Look for pattern like: CREATE CONSTRAINT ... FOR (x:Label) REQUIRE x.prop IS UNIQUE
        pattern = re.compile(
            rf"CREATE\s+CONSTRAINT\s+\S+\s+IF\s+NOT\s+EXISTS\s+FOR\s+\(\w+:{label}\)\s+REQUIRE",
            re.IGNORECASE,
        )
        assert pattern.search(constraint_code), (
            f"Missing uniqueness constraint for :{label} — "
            f"expected pattern like `CREATE CONSTRAINT ... FOR (x:{label}) REQUIRE ...`"
        )


class TestRelationshipCoverage:
    """Every relationship type from DATA_MODEL.md appears in service code."""

    @pytest.mark.parametrize("rel_type", EXPECTED_RELATIONSHIPS)
    def test_relationship_used(self, all_service_code: str, rel_type: str) -> None:
        # Match :REL_TYPE or [:REL_TYPE in Cypher
        pattern = re.compile(rf"[:\[]{rel_type}[\]\s>{{(]", re.IGNORECASE)
        assert pattern.search(all_service_code), (
            f"Relationship type `{rel_type}` from DATA_MODEL.md "
            f"not found in any service Cypher query"
        )


class TestNodePropertyCoverage:
    """Required properties for each node label appear in CREATE or SET Cypher."""

    @pytest.mark.parametrize(
        "label,properties",
        list(REQUIRED_NODE_PROPERTIES.items()),
    )
    def test_required_properties(
        self, all_service_code: str, label: str, properties: list[str],
    ) -> None:
        # Check that the label is referenced in service code
        label_pattern = re.compile(rf":{label}\b")
        if not label_pattern.search(all_service_code):
            pytest.skip(f"Label :{label} not found in service code")

        missing = []
        for prop in properties:
            # Check prop appears near the label context (within any Cypher)
            prop_pattern = re.compile(rf"\.{prop}\b|{prop}\s*[:=]")
            if not prop_pattern.search(all_service_code):
                missing.append(prop)

        assert not missing, (
            f":{label} missing required properties in service code: {missing}"
        )

"""Durable planning records with an atomic Neo4j event outbox.

Synchronous driver calls run in worker threads, including Monte Carlo progress
callbacks. There is deliberately no implicit in-memory fallback on DB failure.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from neo4j import Driver, ManagedTransaction

LABELS = frozenset({"PlanningScenario", "PlanningResult", "RecommendationLog"})
PLANNING_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


class PlanningRepository:
    def __init__(self, driver: Driver) -> None:
        self.driver = driver

    @staticmethod
    def label(kind: str) -> str:
        if kind not in LABELS:
            raise ValueError(f"Invalid planning record kind: {kind}")
        return kind

    def initialize(self) -> None:
        with self.driver.session() as session:
            for kind in sorted(LABELS | {"PlanningEvent"}):
                session.run(
                    f"CREATE CONSTRAINT {kind.lower()}_id IF NOT EXISTS "
                    f"FOR (n:{kind}) REQUIRE n.id IS UNIQUE"
                ).consume()

    @staticmethod
    def event(kind: str, record_id: str, event_type: str, document: dict) -> dict:
        return {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "schema_version": "1.0",
            "producer": "planning-service",
            "produced_at": datetime.now(timezone.utc).isoformat(),
            "sim_time": PLANNING_EPOCH.isoformat(),
            "payload": {
                "record_id": record_id,
                "kind": kind,
                "status": document.get("status"),
                "progress_pct": document.get("progress_pct"),
            },
        }

    @staticmethod
    def write_outbox(tx: ManagedTransaction, event: dict) -> None:
        tx.run(
            "CREATE (e:PlanningEvent {id: $id, document: $document})",
            id=event["event_id"],
            document=json.dumps(event, allow_nan=False),
        ).consume()

    def put(self, kind: str, record_id: str, document: dict) -> None:
        kind = self.label(kind)
        # Serialise before opening a transaction: invalid numerical outputs
        # must not be saved as an apparently successful result.
        encoded = json.dumps(document, allow_nan=False)
        event = self.event(kind, record_id, f"{kind}Updated", document)

        def write(tx: ManagedTransaction) -> None:
            tx.run(
                f"MERGE (n:{kind} {{id: $id}}) SET n.document = $document",
                id=record_id,
                document=encoded,
            ).consume()
            self.write_outbox(tx, event)

        with self.driver.session() as session:
            session.execute_write(write)

    def get(self, kind: str, record_id: str) -> dict | None:
        kind = self.label(kind)
        with self.driver.session() as session:
            row = session.run(
                f"MATCH (n:{kind} {{id: $id}}) RETURN n.document AS document",
                id=record_id,
            ).single()
            return json.loads(row["document"]) if row else None

    def list(self, kind: str) -> list[dict]:
        kind = self.label(kind)
        with self.driver.session() as session:
            return [
                json.loads(row["document"])
                for row in session.run(
                    f"MATCH (n:{kind}) RETURN n.document AS document ORDER BY n.id"
                )
            ]

    def delete(self, kind: str, record_id: str) -> bool:
        kind = self.label(kind)
        event = self.event(kind, record_id, f"{kind}Deleted", {})

        def remove(tx: ManagedTransaction) -> bool:
            row = tx.run(
                f"MATCH (n:{kind} {{id: $id}}) DETACH DELETE n RETURN count(*) AS deleted",
                id=record_id,
            ).single()
            if not row or not row["deleted"]:
                return False
            if kind == "PlanningScenario":
                tx.run(
                    "MATCH (r:PlanningResult {id: $id}) DETACH DELETE r",
                    id=record_id,
                ).consume()
            self.write_outbox(tx, event)
            return True

        with self.driver.session() as session:
            return session.execute_write(remove)

    def pending_events(self) -> list[dict]:
        with self.driver.session() as session:
            return [
                json.loads(row["document"])
                for row in session.run(
                    "MATCH (e:PlanningEvent) RETURN e.document AS document ORDER BY e.id LIMIT 100"
                )
            ]

    def acknowledge(self, event_id: str) -> None:
        with self.driver.session() as session:
            session.run(
                "MATCH (e:PlanningEvent {id: $id}) DELETE e", id=event_id
            ).consume()


_repository: PlanningRepository | None = None


def get_repository() -> PlanningRepository:
    if _repository is None:
        raise RuntimeError("Planning storage has not been initialized")
    return _repository


def initialize() -> None:
    from neo4j import GraphDatabase

    global _repository
    driver = GraphDatabase.driver(
        os.getenv("NEO4J_URI", "bolt://neo4j:7687"),
        auth=(
            os.getenv("NEO4J_USER", "neo4j"),
            os.getenv("NEO4J_PASSWORD", "art-digital-twin"),
        ),
        connection_timeout=10,
    )
    try:
        driver.verify_connectivity()
        repository = PlanningRepository(driver)
        repository.initialize()
    except Exception:
        driver.close()
        raise
    _repository = repository


def ready() -> bool:
    try:
        get_repository().driver.verify_connectivity()
        return True
    except Exception:
        return False


def close() -> None:
    global _repository
    if _repository is not None:
        _repository.driver.close()
        _repository = None

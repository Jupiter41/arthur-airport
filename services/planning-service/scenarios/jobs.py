"""Durable scenario claims, renewable leases and fenced publication."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import logging
import os
import random
import threading
from typing import Callable, TypeVar
from uuid import uuid4

from neo4j import ManagedTransaction

from db.store import get_repository

logger = logging.getLogger(__name__)
T = TypeVar("T")


class LeaseLost(RuntimeError):
    pass


class JobInterrupted(RuntimeError):
    pass


current_lease: ContextVar[JobLease | None] = ContextVar("planning_job_lease", default=None)


def lease_seconds() -> float:
    return max(2.0, float(os.getenv("PLANNING_JOB_LEASE_SECONDS", "30")))


def _locked(tx: ManagedTransaction, scenario_id: str) -> dict | None:
    row = tx.run(
        "MATCH (s:PlanningScenario {id: $id}) "
        "SET s.lease_lock = coalesce(s.lease_lock, 0) + 1 "
        "RETURN s.document AS document, s.lease_token AS token, "
        "coalesce(s.lease_until, 0) AS until, timestamp() AS now",
        id=scenario_id,
    ).single()
    return dict(row) if row else None


def _persist(tx: ManagedTransaction, document: dict) -> None:
    repository = get_repository()
    tx.run("MATCH (s:PlanningScenario {id: $id}) SET s.document = $document",
           id=document["id"], document=json.dumps(document, allow_nan=False)).consume()
    repository.write_outbox(tx, repository.event(
        "PlanningScenario", document["id"], "PlanningScenarioUpdated", document,
    ))


class JobLease:
    def __init__(self, scenario_id: str, token: str, seconds: float,
                 shutdown: threading.Event | None = None) -> None:
        self.scenario_id, self.token, self.seconds = scenario_id, token, seconds
        self.shutdown = shutdown or threading.Event()
        self.lost = threading.Event()
        self.closed = threading.Event()
        self.thread: threading.Thread | None = None

    def check(self) -> None:
        if self.shutdown.is_set():
            raise JobInterrupted("Planning worker is shutting down")
        if self.lost.is_set():
            raise LeaseLost("Planning job lease was replaced or expired")

    def _owned(self, tx: ManagedTransaction) -> dict:
        row = _locked(tx, self.scenario_id)
        if (not row or row["token"] != self.token or row["until"] <= row["now"]
                or json.loads(row["document"])["status"] != "running"):
            raise LeaseLost("Planning job lease was replaced or expired")
        return row

    def _transaction(self, callback: Callable[[ManagedTransaction], T]) -> T:
        with get_repository().driver.session() as session:
            return session.execute_write(callback)

    def renew(self) -> None:
        def update(tx: ManagedTransaction) -> None:
            self._owned(tx)
            tx.run("MATCH (s:PlanningScenario {id: $id}) SET s.lease_until = timestamp() + $ttl",
                   id=self.scenario_id, ttl=int(self.seconds * 1000)).consume()
        self._transaction(update)

    def start(self) -> None:
        def heartbeat() -> None:
            while not self.closed.wait(self.seconds / 3):
                if self.shutdown.is_set():
                    return
                try:
                    self.renew()
                except LeaseLost:
                    self.lost.set()
                    return
                except Exception:
                    logger.warning("Planning lease heartbeat unavailable", exc_info=True)
        self.thread = threading.Thread(target=heartbeat, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=2)

    def save(self, document: dict) -> None:
        self.check()
        if document["id"] != self.scenario_id or document["status"] != "running":
            raise ValueError("Progress must belong to this running scenario")
        def update(tx: ManagedTransaction) -> None:
            self._owned(tx)
            _persist(tx, document)
            tx.run("MATCH (s:PlanningScenario {id: $id}) SET s.lease_until = timestamp() + $ttl",
                   id=self.scenario_id, ttl=int(self.seconds * 1000)).consume()
        self._transaction(update)

    def finish(self, document: dict, results: dict | None = None) -> None:
        self.check()
        if document["id"] != self.scenario_id or document["status"] not in {"completed", "failed"}:
            raise ValueError("Completion must belong to this scenario")
        if (results is None) != (document["status"] == "failed"):
            raise ValueError("Completed scenarios require results; failed scenarios cannot publish results")
        if results is not None and results["scenario_id"] != self.scenario_id:
            raise ValueError("Results must belong to the leased scenario")
        def update(tx: ManagedTransaction) -> None:
            self._owned(tx)
            repository = get_repository()
            if results is not None:
                tx.run("MERGE (r:PlanningResult {id: $id}) SET r.document = $document",
                       id=self.scenario_id, document=json.dumps(results, allow_nan=False)).consume()
                repository.write_outbox(tx, repository.event(
                    "PlanningResult", self.scenario_id, "PlanningResultUpdated", results,
                ))
            else:
                tx.run("MATCH (r:PlanningResult {id: $id}) DETACH DELETE r", id=self.scenario_id).consume()
            _persist(tx, document)
            tx.run("MATCH (s:PlanningScenario {id: $id}) REMOVE s.lease_token SET s.lease_until = 0",
                   id=self.scenario_id).consume()
        self._transaction(update)

    def release(self) -> None:
        def update(tx: ManagedTransaction) -> None:
            row = self._owned(tx)
            document = json.loads(row["document"])
            document["status"] = "pending"
            _persist(tx, document)
            tx.run("MATCH (s:PlanningScenario {id: $id}) REMOVE s.lease_token SET s.lease_until = 0",
                   id=self.scenario_id).consume()
        self._transaction(update)


def claim(scenario_id: str, shutdown: threading.Event | None = None,
          seconds: float | None = None) -> tuple[JobLease, dict] | None:
    ttl = seconds if seconds is not None else lease_seconds()
    token = str(uuid4())
    seed = random.SystemRandom().randrange(1_000_000)

    def acquire(tx: ManagedTransaction) -> dict | None:
        row = _locked(tx, scenario_id)
        if not row:
            return None
        document = json.loads(row["document"])
        if row["token"] == token and document["status"] == "running" and row["until"] > row["now"]:
            return document  # Managed-transaction retry after an ambiguous commit.
        if document["status"] not in {"pending", "running"}:
            return None
        if document["status"] == "running" and row["until"] > row["now"]:
            return None
        document.update(status="running", progress_pct=0, runs_completed=0, error=None, completed_at=None,
                        started_at=datetime.fromtimestamp(row["now"] / 1000, timezone.utc).isoformat(),
                        attempt_count=document.get("attempt_count", 0) + 1)
        if document.get("random_seed") is None:
            document["random_seed"] = seed
        if document.get("financial_rates") is None:
            from _common.financial_rates import load_default_rates, rates_version

            stored = tx.run("MATCH (s:CostRuntime {id: 'latest'}) RETURN s.document AS document").single()
            cost_state = json.loads(stored["document"]) if stored and stored["document"] else {}
            document["financial_rates"] = cost_state.get("rates") or load_default_rates()
            document["financial_rates_version"] = rates_version(document["financial_rates"])
        _persist(tx, document)
        tx.run("MATCH (s:PlanningScenario {id: $id}) "
               "SET s.lease_token = $token, s.lease_until = timestamp() + $ttl",
               id=scenario_id, token=token, ttl=int(ttl * 1000)).consume()
        return document

    with get_repository().driver.session() as session:
        document = session.execute_write(acquire)
    return (JobLease(scenario_id, token, ttl, shutdown), document) if document else None


async def run(shutdown: threading.Event) -> None:
    from scenarios.model import _from_dict
    from scenarios.runner import run_scenario

    while not shutdown.is_set():
        try:
            documents = await asyncio.to_thread(get_repository().list, "PlanningScenario")
            for document in documents:
                if shutdown.is_set():
                    break
                if document["status"] in {"pending", "running"}:
                    await asyncio.to_thread(run_scenario, _from_dict(document), shutdown=shutdown)
        except Exception:
            logger.exception("Planning queue unavailable; durable jobs retained")
        await asyncio.sleep(0.5)

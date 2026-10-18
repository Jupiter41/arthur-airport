"""Lease state transitions and runner fencing; Neo4j behavior is also live-tested."""

from copy import deepcopy
import importlib
import json
import sys
import threading
from unittest.mock import Mock

import pytest

from tests.conftest import import_service_module


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def single(self):
        return self.rows[0] if self.rows else None

    def consume(self):
        pass

    def __iter__(self):
        return iter(self.rows)


class Driver:
    def __init__(self):
        self.db = {"scenarios": {}, "results": {}, "events": []}
        self.now = 1_800_000_000_000
        self.fail_once = None
        self.lock = threading.Lock()

    def session(self):
        driver = self

        class Session:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def execute_write(self, callback):
                with driver.lock:
                    candidate = deepcopy(driver.db)
                    result = callback(Tx(driver, candidate))
                    driver.db = candidate
                    return result

            def run(self, query, **params):
                return Tx(driver, driver.db).run(query, **params)

        return Session()


class Tx:
    def __init__(self, driver, db):
        self.driver, self.db = driver, db

    def run(self, query, **params):
        if self.driver.fail_once and self.driver.fail_once in query:
            self.driver.fail_once = None
            raise RuntimeError("Injected transaction failure")
        key = params.get("id")
        if "MERGE (n:PlanningScenario" in query:
            self.db["scenarios"].setdefault(key, {"token": None, "until": 0})["document"] = params["document"]
        elif "CREATE (e:PlanningEvent" in query:
            self.db["events"].append(json.loads(params["document"]))
        elif "lease_lock" in query:
            row = self.db["scenarios"].get(key)
            return Result([{**row, "now": self.driver.now}] if row else [])
        elif "SET s.document" in query:
            self.db["scenarios"][key]["document"] = params["document"]
        elif "SET s.lease_token" in query:
            self.db["scenarios"][key].update(token=params["token"], until=self.driver.now + params["ttl"])
        elif "REMOVE s.lease_token" in query:
            self.db["scenarios"][key].update(token=None, until=0)
        elif "SET s.lease_until" in query:
            self.db["scenarios"][key]["until"] = self.driver.now + params["ttl"]
        elif "MERGE (r:PlanningResult" in query:
            self.db["results"][key] = params["document"]
        elif "DETACH DELETE r" in query:
            self.db["results"].pop(key, None)
        elif "RETURN n.document" in query:
            source = self.db["scenarios"] if "PlanningScenario" in query else self.db["results"]
            row = source.get(key)
            document = row["document"] if isinstance(row, dict) else row
            return Result([{"document": document}] if row else [])
        else:
            raise AssertionError(query)
        return Result()


@pytest.fixture
def context(monkeypatch):
    for name in list(sys.modules):
        if (name == "scenarios" or name.startswith("scenarios.")) and name != "scenarios.metrics":
            del sys.modules[name]
    store = import_service_module("planning", "db.store")
    driver = Driver()
    repository = store.PlanningRepository(driver)
    monkeypatch.setattr(store, "_repository", repository)
    model = importlib.import_module("scenarios.model")
    jobs = importlib.import_module("scenarios.jobs")
    scenario = model.PlanningScenario(id="synthetic-job", random_seed=0)
    model.store_scenario(scenario)
    return jobs, model, driver, scenario


def test_expired_claim_restarts_with_same_seed_and_fences_old_owner(context):
    jobs, model, driver, scenario = context
    old, document = jobs.claim(scenario.id)
    assert document["random_seed"] == 0 and document["attempt_count"] == 1
    assert jobs.claim(scenario.id) is None
    document["progress_pct"] = 50
    old.save(document)
    driver.now += 31_000
    new, replacement = jobs.claim(scenario.id)
    assert replacement["random_seed"] == 0 and replacement["attempt_count"] == 2
    assert replacement["progress_pct"] == 0
    with pytest.raises(jobs.LeaseLost):
        old.save(document)
    completed = {**replacement, "status": "completed", "progress_pct": 100}
    results = {"scenario_id": scenario.id, "kpis": {"sample": 1}}
    new.finish(completed, results)
    with pytest.raises(jobs.LeaseLost):
        old.finish(completed, results)
    assert model.get_scenario(scenario.id).status == "completed"
    assert model.get_results(scenario.id) == results
    assert jobs.claim(scenario.id) is None


def test_expiry_alone_stops_progress_and_renewal(context):
    jobs, _, driver, scenario = context
    lease, document = jobs.claim(scenario.id)
    driver.now += 31_000
    for operation in (lease.renew, lambda: lease.save(document)):
        with pytest.raises(jobs.LeaseLost):
            operation()


def test_result_status_and_outbox_roll_back_together(context):
    jobs, model, driver, scenario = context
    lease, document = jobs.claim(scenario.id)
    document.update(status="completed", progress_pct=100)
    results = {"scenario_id": scenario.id, "kpis": {"sample": 1}}
    before = deepcopy(driver.db)
    driver.fail_once = "CREATE (e:PlanningEvent"
    with pytest.raises(RuntimeError, match="Injected"):
        lease.finish(document, results)
    assert driver.db == before
    assert model.get_scenario(scenario.id).status == "running"
    assert model.get_results(scenario.id) is None
    lease.finish(document, results)
    assert model.get_scenario(scenario.id).status == "completed"
    assert model.get_results(scenario.id) == results


def test_shutdown_releases_job_without_losing_seed(context):
    jobs, model, _, scenario = context
    stop = threading.Event()
    lease, document = jobs.claim(scenario.id, shutdown=stop)
    stop.set()
    with pytest.raises(jobs.JobInterrupted):
        lease.check()
    lease.release()
    assert model.get_scenario(scenario.id).status == "pending"
    _, restarted = jobs.claim(scenario.id)
    assert restarted["random_seed"] == document["random_seed"]
    assert restarted["attempt_count"] == 2


def test_lease_cannot_write_another_scenario_or_publish_completion_as_progress(context):
    jobs, _, _, scenario = context
    lease, document = jobs.claim(scenario.id)
    with pytest.raises(ValueError):
        lease.save({**document, "id": "other-job"})
    with pytest.raises(ValueError):
        lease.save({**document, "status": "completed"})
    with pytest.raises(ValueError):
        lease.finish({**document, "status": "completed"}, {"scenario_id": "other-job"})


def test_runner_stops_when_replacement_claims_before_progress_save(context, monkeypatch):
    jobs, model, driver, scenario = context
    runner = importlib.import_module("scenarios.runner")

    def simulation(*args, progress_cb, **kwargs):
        driver.now += 31_000
        assert jobs.claim(scenario.id) is not None
        progress_cb(1)
        raise AssertionError("Stale progress should have been fenced")

    monkeypatch.setattr(runner, "_run_monte_carlo", simulation)
    runner.run_scenario(scenario)
    replacement = model.get_scenario(scenario.id)
    assert replacement.status == "running" and replacement.attempt_count == 2
    assert replacement.error is None and replacement.progress_pct == 0
    assert model.get_results(scenario.id) is None


def test_shutdown_guard_precedes_the_next_simulated_day(context):
    jobs, _, _, _ = context
    runner = importlib.import_module("scenarios.runner")
    engine = Mock()

    def check():
        raise jobs.JobInterrupted("Stopped")

    with pytest.raises(jobs.JobInterrupted):
        runner._run_monte_carlo(engine, [None], None, 1, 0, "synthetic", check_cb=check)
    engine.run_day.assert_not_called()

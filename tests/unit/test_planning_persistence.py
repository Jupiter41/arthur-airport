"""Repository-boundary tests for planning durability and outbox delivery."""

import copy
import asyncio
import importlib
from datetime import date

import pytest

from tests.conftest import import_service_module


class MemoryRepository:
    """Injected test adapter; production has no memory fallback."""

    def __init__(self):
        self.records = {}
        self.events = []

    def put(self, kind, key, document):
        self.records[kind, key] = copy.deepcopy(document)

    def get(self, kind, key):
        return copy.deepcopy(self.records.get((kind, key)))

    def list(self, kind):
        return [copy.deepcopy(d) for (k, _), d in self.records.items() if k == kind]

    def delete(self, kind, key):
        if (kind, key) not in self.records:
            return False
        del self.records[kind, key]
        if kind == "PlanningScenario":
            self.records.pop(("PlanningResult", key), None)
        return True

    def pending_events(self):
        return copy.deepcopy(self.events)

    def acknowledge(self, key):
        self.events = [e for e in self.events if e["event_id"] != key]


@pytest.fixture
def context(monkeypatch):
    # Planning namespaces are not shared with any operational service.
    import sys

    for prefix in ("scenarios", "audit"):
        for name in list(sys.modules):
            if (
                name == prefix or name.startswith(prefix + ".")
            ) and name != "scenarios.metrics":
                del sys.modules[name]
    store = import_service_module("planning", "db.store")
    repository = MemoryRepository()
    monkeypatch.setattr(store, "_repository", repository)
    model = importlib.import_module("scenarios.model")
    audit = importlib.import_module("audit.audit_trail")
    jobs = importlib.import_module("scenarios.jobs")

    class Lease:
        """Injected job adapter for runner calculation tests, without DB threads."""

        def __init__(self, key):
            self.key = key

        def start(self):
            pass

        def close(self):
            pass

        def check(self):
            pass

        def save(self, document):
            repository.put("PlanningScenario", self.key, document)

        def finish(self, document, results=None):
            if results is not None:
                repository.put("PlanningResult", self.key, results)
            self.save(document)

        def release(self):
            document = repository.get("PlanningScenario", self.key)
            document["status"] = "pending"
            self.save(document)

    def claim(key, **kwargs):
        document = repository.get("PlanningScenario", key)
        if not document or document["status"] != "pending":
            return None
        document.update(status="running", attempt_count=document.get("attempt_count", 0) + 1)
        if document["random_seed"] is None:
            document["random_seed"] = 42
        repository.put("PlanningScenario", key, document)
        return Lease(key), document

    monkeypatch.setattr(jobs, "claim", claim)
    return store, repository, model, audit


def test_scenario_roundtrip_preserves_all_configuration_across_reads(context):
    _, _, model, _ = context
    scenario = model.PlanningScenario(
        name="Synthetic capacity trial",
        random_seed=0,
        weather_date="2026-01-02",
        demand_multiplier=1.25,
        new_routes=[{"destination": "XAA"}],
        removed_routes=["XBB"],
        interventions=[{"action": "gdp_start"}],
        disruption={"capacity_pct": 0.5},
        parent_scenario_id="parent",
    )
    model.store_scenario(scenario)
    other_worker = model.get_scenario(scenario.id)
    assert other_worker is not scenario
    assert other_worker.to_dict() == scenario.to_dict()
    other_worker.infrastructure.gates_per_terminal["A"] = 1
    assert model.get_scenario(scenario.id).infrastructure.gates_per_terminal["A"] == 14


def test_persisted_progress_is_visible_to_another_reader(context):
    _, _, model, _ = context
    s = model.PlanningScenario(name="Trial")
    model.store_scenario(s)
    s.status, s.progress_pct = "running", 45
    model.store_scenario(s)
    assert model.get_scenario(s.id).progress_pct == 45
    assert model.list_scenarios(status="running")[1] == 1


@pytest.mark.parametrize("suffix", ["", "+00:00"])
def test_completed_job_duration_accepts_legacy_and_aware_utc(context, suffix):
    _, _, model, _ = context
    router = importlib.import_module("routers.planning")
    scenario = model.PlanningScenario(
        status="completed", started_at=f"2026-01-01T12:00:00{suffix}",
        completed_at=f"2026-01-01T12:02:00{suffix}", attempt_count=2,
    )
    model.store_scenario(scenario)
    response = asyncio.run(router.get_scenario_status(scenario.id))
    assert response["elapsed_seconds"] == 120
    assert response["attempt_count"] == 2


def test_replay_keeps_parent_configuration_and_independent_mutable_state(context, monkeypatch):
    _, _, model, _ = context
    router = importlib.import_module("routers.counterfactual")
    parent = model.PlanningScenario(
        name="Synthetic parent", status="completed", progress_pct=100, runs_completed=4,
        random_seed=42, weather_date="2026-01-02", demand_multiplier=1.25,
        new_routes=[{"destination": "XAA"}], removed_routes=["XBB"],
        disruption={"capacity_pct": 0.5}, completed_at="2026-01-03T00:00:00",
        attempt_count=3,
    )
    saved = []
    monkeypatch.setattr(router, "store_scenario", saved.append)
    child = router._spawn_replay_scenario(parent, [], None, "timing change")
    assert saved == [child]
    assert child.id != parent.id and child.parent_scenario_id == parent.id
    assert (child.status, child.progress_pct, child.runs_completed, child.completed_at) == ("pending", 0, 0, None)
    assert child.attempt_count == 0
    for key in ("random_seed", "weather_date", "demand_multiplier", "new_routes", "removed_routes", "disruption"):
        assert getattr(child, key) == getattr(parent, key)
    child.infrastructure.gates_per_terminal["A"] = 1
    child.new_routes[0]["destination"] = "XCC"
    child.disruption["capacity_pct"] = 0.1
    assert parent.infrastructure.gates_per_terminal["A"] == 14
    assert parent.new_routes[0]["destination"] == "XAA"
    assert parent.disruption["capacity_pct"] == 0.5
    assert child.to_summary()["parent_scenario_id"] == parent.id


def test_deletion_blocks_active_jobs_and_removes_completed_results(context):
    _, _, model, _ = context
    s = model.PlanningScenario()
    model.store_scenario(s)
    with pytest.raises(ValueError, match="pending or running"):
        model.delete_scenario(s.id)
    s.status = "completed"
    model.store_scenario(s)
    model.store_results(s.id, {"kpis": {"avg_delay_minutes": {"mean": 4}}})
    assert model.delete_scenario(s.id)
    assert model.get_scenario(s.id) is None
    assert model.get_results(s.id) is None


def test_audit_accuracy_compares_only_measured_recommendations(context):
    _, _, _, audit = context
    measured = audit.log_recommendation("Open lane", "security_lane", 100, 0.9)
    pending_measurement = audit.log_recommendation(
        "Hold flight", "hold_flight", 900, 0.8
    )
    audit.mark_applied(measured.id, "2026-01-01T10:00:00Z")
    audit.mark_applied(pending_measurement.id, "2026-01-01T10:00:00Z")
    audit.record_outcome(measured.id, 100)
    summary = audit.get_audit_summary()
    assert summary["prediction_accuracy_pct"] == 100
    assert summary["measured_count"] == 1
    assert audit.get_audit_log()[1] == 2


def test_storage_unavailable_never_returns_worker_local_success(context, monkeypatch):
    store, _, model, _ = context
    monkeypatch.setattr(store, "_repository", None)
    with pytest.raises(RuntimeError, match="initialized"):
        model.store_scenario(model.PlanningScenario())


def test_failed_delivery_retains_outbox_and_retry_keeps_event_identity(context):
    _, repository, _, _ = context
    outbox = importlib.import_module("db.outbox")
    repository.events = [
        {"event_id": "stable-1", "payload": {"record_id": "scenario-1"}}
    ]

    class Producer:
        failure = "broker failure"
        messages = []

        def produce(self, **kwargs):
            self.messages.append(kwargs["value"])
            kwargs["callback"](self.failure, None)

    producer = Producer()
    with pytest.raises(RuntimeError, match="retained"):
        outbox.publish_pending(producer)
    assert len(repository.events) == 1
    producer.failure = None
    assert outbox.publish_pending(producer) == 1
    assert repository.events == []
    assert producer.messages[0] == producer.messages[1]


def test_record_and_outbox_are_written_in_one_transaction(context):
    store, _, _, _ = context
    transactions = []

    class Transaction:
        calls = []

        def run(self, query, **params):
            self.calls.append((query, params))
            return self

        def consume(self):
            pass

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute_write(self, fn):
            tx = Transaction()
            transactions.append(tx)
            return fn(tx)

    class Driver:
        def session(self):
            return Session()

    repository = store.PlanningRepository(Driver())
    repository.put("PlanningScenario", "s1", {"status": "pending"})
    assert len(transactions) == 1
    assert len(transactions[0].calls) == 2
    assert "PlanningScenario" in transactions[0].calls[0][0]
    assert "PlanningEvent" in transactions[0].calls[1][0]
    with pytest.raises(ValueError):
        repository.put("Flight", "f1", {})


def test_runner_saves_seed_progress_results_and_negative_benefit(context, monkeypatch):
    _, repository, model, _ = context
    runner = importlib.import_module("scenarios.runner")
    results = importlib.import_module("engine.results")
    benefits = importlib.import_module("finance.benefit_extractor")
    seeds = []

    def simulate(engine, dates, infra, runs, base_seed, label, progress_cb, **kwargs):
        seeds.append(base_seed)
        progress_cb(1)
        # A separate read represents the status request handled by another worker.
        assert model.get_scenario("trial").progress_pct > 0
        return [
            [
                results.DayResult(
                    sim_date=date(2026, 1, 1),
                    infrastructure_label="trial",
                    total_flights=10,
                )
            ]
        ]

    monkeypatch.setattr(runner, "_run_monte_carlo", simulate)
    monkeypatch.setattr(
        runner,
        "extract_annual_benefit",
        lambda *a: benefits.AnnualBenefitBreakdown(
            total_annual_benefit=-500,
        ),
    )
    scenario = model.PlanningScenario(id="trial", name="Trial", capex_eur=1000)
    model.store_scenario(scenario)
    runner.run_scenario(scenario)
    saved = model.get_scenario(scenario.id)
    assert saved.status == "completed"
    assert saved.progress_pct == 100
    assert saved.runs_completed == 2
    assert seeds == [saved.random_seed, saved.random_seed]
    financials = model.get_results(scenario.id)["financials"]
    assert financials["annual_benefit_eur"] == -500
    assert financials["npv_eur"] < -1000


def test_failed_result_save_cannot_publish_completed_status(context, monkeypatch):
    _, repository, model, _ = context
    runner = importlib.import_module("scenarios.runner")
    results = importlib.import_module("engine.results")
    monkeypatch.setattr(
        runner,
        "_run_monte_carlo",
        lambda *a, **kw: [
            [
                results.DayResult(
                    sim_date=date(2026, 1, 1),
                    infrastructure_label="trial",
                    total_flights=10,
                )
            ]
        ],
    )
    original_put = repository.put

    def put(kind, key, document):
        if kind == "PlanningResult":
            raise RuntimeError("Result storage unavailable")
        original_put(kind, key, document)

    monkeypatch.setattr(repository, "put", put)
    scenario = model.PlanningScenario(id="failed-trial")
    model.store_scenario(scenario)
    runner.run_scenario(scenario)
    saved = model.get_scenario(scenario.id)
    assert saved.status == "failed"
    assert "Result storage unavailable" in saved.error
    assert model.get_results(scenario.id) is None

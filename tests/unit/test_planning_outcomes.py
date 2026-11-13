"""G7/G8 planning: automatic recommendation outcomes and recoverable ML training."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import import_service_module

NOW = datetime(2026, 3, 2, 12, 0, tzinfo=timezone.utc)


class Repository:
    """In-memory PlanningRepository double with the same atomic update contract."""

    def __init__(self):
        self.records: dict[tuple[str, str], dict] = {}
        self.outbox: list[dict] = []

    def put(self, kind, record_id, document):
        self.records[kind, record_id] = deepcopy(document)
        self.outbox.append({"event_type": f"{kind}Updated", "payload": {"record_id": record_id}})

    def get(self, kind, record_id):
        return deepcopy(self.records.get((kind, record_id)))

    def list(self, kind):
        return [deepcopy(v) for (k, _), v in sorted(self.records.items()) if k == kind]

    def update(self, kind, record_id, mutate, extra_event=None):
        current = self.get(kind, record_id)
        if current is None:
            return None
        updated = mutate(current)
        if updated is None:
            return None
        self.put(kind, record_id, updated)
        if extra_event is not None:
            self.outbox.append(deepcopy(extra_event))
        return updated


@pytest.fixture
def planning(monkeypatch):
    measurer = import_service_module("planning", "audit.outcome_measurer")
    trail = __import__("audit.audit_trail", fromlist=["record_measured_outcome"])
    repository = Repository()
    monkeypatch.setattr(measurer, "get_repository", lambda: repository)
    monkeypatch.setattr(trail, "get_repository", lambda: repository)
    return measurer, trail, repository


def _entry(**kw):
    base = {"id": "r1", "was_applied": True, "actual_saving_eur": None, "target_type": "Terminal",
            "target_id": "T-A", "applied_at": (NOW - timedelta(minutes=30)).isoformat(),
            "predicted_saving_eur": 500.0, "sim_day": 2}
    base.update(kw)
    return base


def test_due_requires_applied_target_and_elapsed_sim_window(planning):
    measurer, *_ = planning
    assert measurer.due([_entry()], NOW, 30) == [_entry()]
    assert measurer.due([_entry(applied_at=(NOW - timedelta(minutes=29)).isoformat())], NOW, 30) == []
    assert measurer.due([_entry(was_applied=False)], NOW, 30) == []
    assert measurer.due([_entry(actual_saving_eur=1.0)], NOW, 30) == []
    assert measurer.due([_entry(target_type="")], NOW, 30) == []
    assert measurer.due([_entry(applied_at="not-a-time")], NOW, 30) == []


def test_difference_in_differences_against_untreated_units(planning):
    measurer, *_ = planning
    costs = {"T-A": {"pre": 1000.0, "post": 400.0},
             "T-B": {"pre": 800.0, "post": 600.0}, "T-C": {"pre": 500.0, "post": 300.0}}
    attribution = measurer.attribute("T-A", costs, 30)
    assert attribution["method"] == "difference_in_differences"
    assert attribution["treated_change_eur"] == -600
    assert attribution["control_change_eur"] == -200
    assert attribution["actual_saving_eur"] == 400          # not the naive 600
    assert attribution["counterfactual_post_eur"] == 800
    assert attribution["calibration_eligible"] is True and attribution["causal_claim"] is False
    alone = measurer.attribute("T-A", {"T-A": costs["T-A"]}, 30)
    assert alone["method"] == "pre_post" and alone["calibration_eligible"] is False
    assert alone["actual_saving_eur"] == 600


def test_measured_outcome_is_atomic_idempotent_and_emits_fact(planning):
    measurer, trail, repository = planning
    repository.put("RecommendationLog", "r1", _entry())
    attribution = measurer.attribute("T-A", {"T-A": {"pre": 1000.0, "post": 400.0},
                                             "T-B": {"pre": 800.0, "post": 600.0}}, 30)
    stored = trail.record_measured_outcome("r1", attribution, NOW.isoformat())
    assert stored["actual_saving_eur"] == 400 and stored["prediction_error_eur"] == 100
    assert stored["outcome_source"] == "automatic" and stored["measurement_sim_time"] == NOW.isoformat()
    fact, = [e for e in repository.outbox if e["event_type"] == "RecommendationOutcomeMeasured"]
    assert fact["payload"]["actual_saving_eur"] == 400 and fact["sim_time"] == NOW.isoformat()
    assert trail.record_measured_outcome("r1", dict(attribution, actual_saving_eur=1), NOW.isoformat()) is None
    assert len([e for e in repository.outbox if e["event_type"] == "RecommendationOutcomeMeasured"]) == 1
    summary = trail.get_audit_summary()
    assert summary["automatic_measured_count"] == 1 and summary["counterfactual_attributed_count"] == 1


def test_measurement_pass_uses_sim_state_and_cost_windows(planning, monkeypatch):
    measurer, trail, repository = planning
    repository.put("RecommendationLog", "r1", _entry())
    monkeypatch.setattr(measurer, "current_sim_state", lambda: (NOW, 2))
    seen = {}

    def costs(target_type, applied, window, now, day_now):
        seen.update(target_type=target_type, applied=applied, window=window)
        return {"T-A": {"pre": 300.0, "post": 100.0}, "T-B": {"pre": 300.0, "post": 300.0}}

    monkeypatch.setattr(measurer, "window_costs", costs)
    assert measurer.measure_due() == 1
    assert measurer.measure_due() == 0
    assert seen == {"target_type": "Terminal", "applied": NOW - timedelta(minutes=30), "window": 30}
    assert repository.get("RecommendationLog", "r1")["actual_saving_eur"] == 200


def test_cost_day_window_is_padded(planning):
    measurer, *_ = planning
    applied = NOW - timedelta(days=1, minutes=10)
    days = measurer._days(NOW, 5, applied - timedelta(minutes=30), applied + timedelta(minutes=30))
    assert days == [3, 4, 5]


def test_interrupted_training_is_rerun_on_restart(monkeypatch, tmp_path):
    jobs = import_service_module("planning", "ml.training_jobs")
    repository = Repository()
    monkeypatch.setattr(jobs, "get_repository", lambda: repository)
    dataset = tmp_path / "synthetic.csv"
    dataset.write_text("YEAR,MONTH\n")
    calls = []
    trained = {"value": False}

    def pipeline(path):
        calls.append(path)
        trained["value"] = True
        return {"demand": {"trained": True}, "delay": {"trained": True}}

    pipeline_module = __import__("ml.training_pipeline", fromlist=["run_training_pipeline"])
    monkeypatch.setattr(pipeline_module, "run_training_pipeline", pipeline)
    monkeypatch.setattr(jobs, "_trained_in_process", lambda: trained["value"])
    # A crash mid-training left the durable record running; no model in memory.
    repository.put("ModelTrainingRun", jobs.RUN_ID, {"id": jobs.RUN_ID, "status": "running",
                                                     "dataset_path": str(dataset), "attempt_count": 1,
                                                     "dataset_sha256": jobs.dataset_hash(str(dataset))})
    restored = jobs.restore()
    assert calls == [str(dataset)]
    assert restored["status"] == "completed" and restored["attempt_count"] == 2
    assert restored["recovered"] is True and restored["dataset_changed"] is False
    # Already trained in this process: nothing to recover.
    assert jobs.restore()["attempt_count"] == 2 and calls == [str(dataset)]


def test_restore_labels_changed_or_missing_dataset(monkeypatch, tmp_path):
    jobs = import_service_module("planning", "ml.training_jobs")
    repository = Repository()
    monkeypatch.setattr(jobs, "get_repository", lambda: repository)
    monkeypatch.setattr(jobs, "_trained_in_process", lambda: False)
    repository.put("ModelTrainingRun", jobs.RUN_ID, {"id": jobs.RUN_ID, "status": "completed",
                                                     "dataset_path": str(tmp_path / "gone.csv")})
    assert jobs.restore()["status"] == "failed"
    dataset = tmp_path / "changed.csv"
    dataset.write_text("new contents")
    pipeline_module = __import__("ml.training_pipeline", fromlist=["run_training_pipeline"])
    monkeypatch.setattr(pipeline_module, "run_training_pipeline",
                        lambda path: {"demand": {"trained": True}, "delay": {"trained": True}})
    repository.put("ModelTrainingRun", jobs.RUN_ID, {"id": jobs.RUN_ID, "status": "completed",
                                                     "dataset_path": str(dataset), "dataset_sha256": "old"})
    restored = jobs.restore()
    assert restored["dataset_changed"] is True and restored["dataset_sha256"] == "old"
    assert repository.get("ModelTrainingRun", jobs.RUN_ID)["status"] == "completed"

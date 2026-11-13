"""Durable, recoverable planning ML training (roadmap G7).

The demand and delay models live in process memory and are trained from the
reference BTS dataset. A ``ModelTrainingRun`` record in Neo4j stores the
requested dataset, its content hash, status and attempt count. When a process
restarts — after a crash mid-training or simply losing its in-memory models —
:func:`restore` re-runs the recorded training request. Training is deterministic
(fixed ``random_state``), so a recovered attempt rebuilds the same models from
the same dataset; a changed dataset is detected and labelled rather than hidden.
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

import structlog

from db.store import get_repository

logger = structlog.get_logger(__name__)

RUN_ID = "planning-ml"
_lock = threading.Lock()


def dataset_hash(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1 << 20), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _now() -> str:
    # Job metadata only; never simulation business time.
    return datetime.now(timezone.utc).isoformat()


def _trained_in_process() -> bool:
    from ml.delay_model import get_delay_model
    from ml.demand_model import get_demand_model

    return get_demand_model().is_trained and get_delay_model().is_trained


def _execute(document: dict, *, recovered: bool) -> dict:
    from ml.training_pipeline import run_training_pipeline

    repository = get_repository()
    current_hash = dataset_hash(document["dataset_path"])
    document.update(
        status="running", started_at=_now(), completed_at=None, error=None,
        attempt_count=int(document.get("attempt_count", 0)) + 1, recovered=recovered,
        dataset_changed=bool(document.get("dataset_sha256")) and current_hash != document.get("dataset_sha256"),
    )
    if not recovered or not document.get("dataset_sha256"):
        document["dataset_sha256"] = current_hash
    repository.put("ModelTrainingRun", RUN_ID, document)
    try:
        results = run_training_pipeline(document["dataset_path"])
    except Exception as exc:  # recorded, then surfaced to the caller
        document.update(status="failed", error=str(exc)[:500], completed_at=_now())
        repository.put("ModelTrainingRun", RUN_ID, document)
        raise
    trained = all(isinstance(results.get(k), dict) and results[k].get("trained") for k in ("demand", "delay"))
    document.update(status="completed" if trained else "failed", results=results, completed_at=_now(),
                    error=None if trained else "training produced no model; see results")
    repository.put("ModelTrainingRun", RUN_ID, document)
    return document


def request_training(dataset_path: str) -> dict:
    """Record the training request durably, then train (synchronously, in a worker thread)."""
    with _lock:
        previous = get_repository().get("ModelTrainingRun", RUN_ID) or {}
        document = {"id": RUN_ID, "dataset_path": dataset_path, "requested_at": _now(),
                    "attempt_count": previous.get("attempt_count", 0)}
        return _execute(document, recovered=False)


def restore() -> dict | None:
    """Re-run the recorded training after a restart (interrupted or completed-but-lost)."""
    with _lock:
        document = get_repository().get("ModelTrainingRun", RUN_ID)
        if not document or document.get("status") not in {"running", "completed"}:
            return None
        if _trained_in_process():
            return document
        if not Path(document.get("dataset_path", "")).is_file():
            document.update(status="failed", error="recorded training dataset is unavailable",
                            completed_at=_now())
            get_repository().put("ModelTrainingRun", RUN_ID, document)
            return document
        logger.info("restoring planning ML models from durable training run",
                    previous_status=document.get("status"), attempt=document.get("attempt_count"))
        try:
            return _execute(document, recovered=True)
        except Exception:
            logger.exception("planning ML training recovery failed")
            return get_repository().get("ModelTrainingRun", RUN_ID)


def status() -> dict | None:
    return get_repository().get("ModelTrainingRun", RUN_ID)

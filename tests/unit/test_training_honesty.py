"""Training may report completion only for an implemented, successful job."""

import asyncio
import io
from datetime import datetime, timezone

import pytest

from tests.conftest import import_service_module


@pytest.mark.parametrize("kind", ["forecast", "anomaly", "unknown"])
def test_unimplemented_training_rejected_without_fake_history(kind):
    module = import_service_module("analysis", "services.training_manager")
    manager = module.TrainingManager()
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(manager.start_training(kind))
    assert manager.runs == []
    assert manager.active_run is None


def test_successful_exit_without_model_is_failure(tmp_path):
    module = import_service_module("analysis", "services.training_manager")
    manager = module.TrainingManager()
    run = module.TrainingRun(
        id="trial",
        model_type="rl",
        status="running",
        total_timesteps=1000,
        started_at=datetime.now(timezone.utc).isoformat(),
        output_path=str(tmp_path / "missing.zip"),
    )

    class Process:
        returncode = 0
        stdout = io.BytesIO(b"")

        def poll(self):
            return 0

    manager._process = Process()
    asyncio.run(manager._monitor_process(run))
    assert run.status == "failed"
    assert "no model artifact" in run.error
    assert run.progress_pct != 100


def test_successful_job_promotes_new_archive_atomically(tmp_path, monkeypatch):
    import zipfile

    module = import_service_module("analysis", "services.training_manager")
    monkeypatch.setattr(module, "MODELS_DIR", tmp_path)
    monkeypatch.delenv("RL_MODEL_PATH", raising=False)
    artifact = tmp_path / "new-policy.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        archive.writestr("synthetic-test-artifact", "test")
    manager = module.TrainingManager()
    run = module.TrainingRun(id="trial", model_type="rl", output_path=str(artifact))

    class Process:
        returncode = 0
        stdout = io.BytesIO(b"")

        def poll(self):
            return 0

    manager._process = Process()
    asyncio.run(manager._monitor_process(run))
    assert run.status == "completed"
    assert run.progress_pct == 100
    assert run.progress_estimated is False
    assert (tmp_path / "rl_policy.zip").read_bytes() == artifact.read_bytes()

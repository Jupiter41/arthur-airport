"""Train and reload a real small PPO policy; this is a mechanics test only."""

import os
from pathlib import Path
import subprocess
import sys


def test_real_ppo_training_without_tensorboard_creates_usable_policy(tmp_path):
    root = Path(__file__).resolve().parents[2]
    artifact = tmp_path / "synthetic-policy.zip"
    # Run with the service's own import namespace to avoid cross-service modules.
    result = subprocess.run(
        [sys.executable, "training/train_rl.py", "--timesteps", "1024",
         "--eval-episodes", "1", "--threads", "1", "--output", str(artifact)],
        cwd=root / "services/analysis-service",
        env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"},
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert artifact.exists() and artifact.stat().st_size > 0

    from stable_baselines3 import PPO
    import numpy as np

    model = PPO.load(artifact, device="cpu")
    action, _ = model.predict(np.zeros(22, dtype=np.float32), deterministic=True)
    assert 0 <= int(action) < 7


def test_policy_observation_includes_actual_flight_status_and_observed_wait():
    from tests.conftest import import_service_module
    import importlib

    env_module = import_service_module("analysis", "services.rl.env")
    state_module = importlib.import_module("services.state")
    state = state_module.OperationalState()
    state.security["Terminal B"].observed_wait_minutes = 35
    state.flights["inbound"] = state_module.FlightState(flight_id="inbound", status="approach")
    state.flights["landed"] = state_module.FlightState(flight_id="landed", status="taxiing")
    snapshot = env_module.state_from_operational(state, active_bottleneck_count=2)
    environment = env_module.AirportOpsEnv(initial_state=snapshot)
    obs, _ = environment.reset()
    values = dict(zip(env_module.STATE_LABELS, obs))
    assert values["security_wait_B"] == 35
    assert values["flights_approaching"] == 1
    assert values["flights_landed"] == 1
    assert values["active_bottleneck_count"] == 2
    environment.close()


def test_real_ppo_checkpoint_resumes_remaining_timesteps(tmp_path):
    """G7: an interrupted run continues from its atomic checkpoint, not from zero."""
    import json

    root = Path(__file__).resolve().parents[2]
    checkpoints = tmp_path / "checkpoints"
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}

    def train(total, output, *extra):
        return subprocess.run(
            [sys.executable, "training/train_rl.py", "--timesteps", str(total), "--eval-episodes", "1",
             "--threads", "1", "--seed", "7", "--output", str(output),
             "--checkpoint-dir", str(checkpoints), "--checkpoint-freq", "512", *extra],
            cwd=root / "services/analysis-service", env=env, capture_output=True, text=True, timeout=120,
        )

    first = train(1024, tmp_path / "first.zip")
    assert first.returncode == 0, first.stdout + first.stderr
    checkpoint = json.loads((checkpoints / "checkpoint.json").read_text())["timesteps"]
    assert checkpoint >= 512 and (checkpoints / "latest.zip").is_file()
    assert not list(checkpoints.glob("*.partial.zip"))

    resumed = train(2048, tmp_path / "resumed.zip", "--resume", str(checkpoints / "latest.zip"))
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert "Resuming PPO from checkpoint" in resumed.stdout + resumed.stderr

    from stable_baselines3 import PPO

    model = PPO.load(tmp_path / "resumed.zip", device="cpu")
    assert 2048 <= model.num_timesteps < 2048 + 1024   # continued, did not restart at zero
    progress = json.loads((checkpoints / "progress.json").read_text())
    assert progress["completed"] is True and progress["timesteps"] == model.num_timesteps


def test_real_ppo_survives_sigkill_and_resumes_from_last_checkpoint(tmp_path):
    """G7: an abrupt kill leaves a valid checkpoint; resumption completes the run."""
    import json
    import signal
    import time

    root = Path(__file__).resolve().parents[2]
    checkpoints = tmp_path / "checkpoints"
    env = {**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    base = [sys.executable, "training/train_rl.py", "--timesteps", "200000", "--eval-episodes", "1",
            "--threads", "1", "--seed", "11", "--checkpoint-dir", str(checkpoints),
            "--checkpoint-freq", "512"]
    process = subprocess.Popen(base + ["--output", str(tmp_path / "killed.zip")],
                               cwd=root / "services/analysis-service", env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 90
        while not (checkpoints / "checkpoint.json").exists():
            assert process.poll() is None and time.monotonic() < deadline
            time.sleep(0.2)
        time.sleep(0.5)
    finally:
        process.send_signal(signal.SIGKILL)
        process.wait()
    assert not (tmp_path / "killed.zip").exists()
    reached = json.loads((checkpoints / "checkpoint.json").read_text())["timesteps"]
    assert reached >= 512

    total = reached + 1024
    command = [*base, "--output", str(tmp_path / "recovered.zip"), "--resume", str(checkpoints / "latest.zip")]
    command[command.index("--timesteps") + 1] = str(total)
    resumed = subprocess.run(command, cwd=root / "services/analysis-service", env=env,
                             capture_output=True, text=True, timeout=120)
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    from stable_baselines3 import PPO

    assert PPO.load(tmp_path / "recovered.zip", device="cpu").num_timesteps >= total

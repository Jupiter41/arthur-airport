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

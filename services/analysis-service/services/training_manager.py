"""Training manager — track and control ML model training runs.

Provides a lightweight in-memory registry of training runs (RL, anomaly,
forecasting) with status tracking. Actual training is delegated to the
existing training scripts via subprocess.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import shutil
import zipfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"


@dataclass
class TrainingRun:
    """A single training run record."""
    id: str
    model_type: str  # rl, anomaly, forecast
    status: str = "queued"  # queued | running | completed | failed | stopped
    started_at: str | None = None
    completed_at: str | None = None
    progress_pct: float = 0.0
    total_timesteps: int = 0
    current_timesteps: int = 0
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    output_path: str | None = None
    progress_estimated: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_type": self.model_type,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "progress_pct": round(self.progress_pct, 1),
            "progress_estimated": self.progress_estimated,
            "total_timesteps": self.total_timesteps,
            "current_timesteps": self.current_timesteps,
            "metrics": self.metrics,
            "error": self.error,
            "output_path": self.output_path,
        }


class TrainingManager:
    """Manages training runs with at-most-one concurrent run."""

    def __init__(self) -> None:
        self.runs: list[TrainingRun] = []
        self.active_run: TrainingRun | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._monitor_task: asyncio.Task[None] | None = None

    def get_status(self) -> dict[str, Any]:
        """Return current training status summary."""
        models = self._list_models()
        return {
            "active_run": self.active_run.to_dict() if self.active_run else None,
            "history": [r.to_dict() for r in self.runs[-20:]],
            "available_models": models,
            "available_training_types": ["rl"],
        }

    def get_config(self) -> dict[str, Any]:
        """Return training-related environment config and model status."""
        from services.rl.agent import is_loaded as rl_is_loaded, MODEL_PATH as rl_model_path

        rl_model_exists = Path(rl_model_path).exists()
        models_dir = str(MODELS_DIR)
        models_dir_exists = MODELS_DIR.exists()

        # Collect all .zip and .lgbm model files
        model_files: list[str] = []
        if models_dir_exists:
            for p in sorted(MODELS_DIR.rglob("*")):
                if p.is_file() and p.suffix in (".zip", ".lgbm", ".pkl"):
                    model_files.append(str(p.relative_to(MODELS_DIR)))

        return {
            "rl_model_path": rl_model_path,
            "rl_model_exists": rl_model_exists,
            "rl_model_loaded": rl_is_loaded(),
            "models_dir": models_dir,
            "models_dir_exists": models_dir_exists,
            "model_files": model_files,
            "env": {
                "RL_MODEL_PATH": os.getenv("RL_MODEL_PATH", "(not set)"),
                "RL_TIMESTEPS": os.getenv("RL_TIMESTEPS", "(not set)"),
                "RL_OUTPUT": os.getenv("RL_OUTPUT", "(not set)"),
                "LLM_BASE_URL": os.getenv("LLM_BASE_URL", "(not set)"),
                "LLM_MODEL": os.getenv("LLM_MODEL", "(not set)"),
                "LLM_API_KEY": "***" if os.getenv("LLM_API_KEY") else "(not set)",
            },
        }

    def _list_models(self) -> list[dict[str, Any]]:
        """List trained model files in the models directory."""
        models: list[dict[str, Any]] = []
        if not MODELS_DIR.exists():
            return models
        for p in sorted(MODELS_DIR.rglob("*.zip")):
            stat = p.stat()
            models.append({
                "path": str(p.relative_to(MODELS_DIR)),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
            })
        return models

    async def start_training(
        self,
        model_type: str = "rl",
        timesteps: int = 50000,
    ) -> TrainingRun:
        """Start a new training run."""
        if self.active_run and self.active_run.status == "running":
            raise ValueError("A training run is already in progress")

        if model_type != "rl":
            raise ValueError(f"Training {model_type!r} is unavailable; only RL training is implemented")
        if type(timesteps) is not int or not 1 <= timesteps <= 10_000_000:
            raise ValueError("timesteps must be an integer between 1 and 10000000")
        run_id = f"train-{model_type}-{uuid4().hex[:12]}"
        output_path = str(MODELS_DIR / f"{run_id}.zip")

        run = TrainingRun(
            id=run_id,
            model_type=model_type,
            status="running",
            started_at=datetime.now(timezone.utc).isoformat(),
            total_timesteps=timesteps,
            output_path=output_path,
        )

        self.active_run = run
        self.runs.append(run)

        # Launch training in subprocess
        if model_type == "rl":
            script = str(Path(__file__).parent.parent / "training" / "train_rl.py")
            cmd = [
                sys.executable, "-u", script,
                "--timesteps", str(timesteps),
                "--output", output_path,
            ]

        try:
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            env = {**os.environ, "RL_TIMESTEPS": str(timesteps)}
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
            )
            # Start async monitor
            self._monitor_task = asyncio.create_task(self._monitor_process(run))
        except Exception as e:
            run.status = "failed"
            run.error = str(e)
            run.completed_at = datetime.now(timezone.utc).isoformat()
            self.active_run = None
            logger.error("Failed to start training: %s", e)

        return run

    async def _monitor_process(self, run: TrainingRun) -> None:
        """Monitor the training subprocess until completion."""
        proc = self._process
        if proc is None:
            return

        async def drain_output() -> str:
            def read_output() -> str:
                from collections import deque
                tail = deque(maxlen=100)
                if proc.stdout:
                    for line in iter(proc.stdout.readline, b""):
                        tail.append(line.decode(errors="replace"))
                return "".join(tail)
            return await asyncio.to_thread(read_output)

        output_task = asyncio.create_task(drain_output())
        try:
            while proc.poll() is None:
                # Estimate progress based on elapsed time (rough heuristic)
                if run.started_at:
                    elapsed = time.time() - datetime.fromisoformat(run.started_at).timestamp()
                    # Rough estimate: ~1000 timesteps/sec for PPO with MlpPolicy
                    estimated_steps = int(elapsed * 1000)
                    run.current_timesteps = min(estimated_steps, max(0, run.total_timesteps - 1))
                    run.progress_pct = (run.current_timesteps / run.total_timesteps) * 100
                await asyncio.sleep(2)

            # Process completed
            output = await output_task
            if (proc.returncode == 0 and run.output_path
                    and Path(run.output_path).is_file()
                    and zipfile.is_zipfile(run.output_path)):
                # Preserve the previous usable model until a successful job has
                # produced a new archive. Atomic replacement also survives restart.
                canonical = Path(os.getenv("RL_MODEL_PATH", str(MODELS_DIR / "rl_policy.zip")))
                canonical.parent.mkdir(parents=True, exist_ok=True)
                staged = canonical.with_suffix(".pending")
                shutil.copyfile(run.output_path, staged)
                staged.replace(canonical)
                run.status = "completed"
                run.progress_pct = 100.0
                run.progress_estimated = False
                run.current_timesteps = run.total_timesteps
                logger.info("Training run %s completed successfully", run.id)
            else:
                run.status = "failed"
                run.error = output[-500:] if output else (
                    "Training produced no model artifact or invalid archive" if proc.returncode == 0
                    else f"Exit code {proc.returncode}"
                )
                logger.error("Training run %s failed: %s", run.id, run.error)
        except asyncio.CancelledError:
            run.status = "stopped"
            logger.info("Training run %s stopped", run.id)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.exception("Training finalization failed")
        finally:
            run.completed_at = datetime.now(timezone.utc).isoformat()
            self.active_run = None
            self._process = None

    async def stop_training(self) -> bool:
        """Terminate and reap the active job before permitting another run."""
        proc = self._process
        if proc is None or proc.poll() is not None:
            return False
        proc.terminate()
        try:
            await asyncio.to_thread(proc.wait, timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            await asyncio.to_thread(proc.wait)
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        return True


# Singleton instance
manager = TrainingManager()

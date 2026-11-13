"""Training manager — durable, recoverable ML training runs (roadmap G7).

Runs are persisted in Neo4j by ``services.training_store`` with a renewable
lease and fencing token. The PPO subprocess writes atomic checkpoints and a
progress file into the run's checkpoint directory. If the service exits
abruptly the lease expires and the next worker (on restart, or another replica)
claims the run, increments ``attempt_count`` and resumes from the latest
checkpoint with the same seed and configuration. A graceful shutdown releases
the run back to ``queued``; an explicit operator stop is terminal. A replaced
or expired owner cannot publish progress, promote a model or finish the run.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import subprocess
import sys
import shutil
import zipfile
import time
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent.parent / "models"


def artifacts_dir() -> Path:
    """Durable artifact root (mount a volume here); defaults to the legacy models dir."""
    return Path(os.getenv("TRAINING_ARTIFACTS_DIR", str(MODELS_DIR)))


def lease_seconds() -> float:
    return max(2.0, float(os.getenv("TRAINING_LEASE_SECONDS", "30")))


def recovery_poll_seconds() -> float:
    return max(0.5, float(os.getenv("TRAINING_RECOVERY_POLL_SECONDS", "5")))


def checkpoint_every(timesteps: int) -> int:
    configured = int(os.getenv("TRAINING_CHECKPOINT_TIMESTEPS", "0") or 0)
    return configured if configured > 0 else max(1000, timesteps // 20)


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
    seed: int | None = None
    attempt_count: int = 0
    checkpoint_dir: str | None = None
    resumed_from_timesteps: int = 0
    created_at: str | None = None

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
            "seed": self.seed,
            "attempt_count": self.attempt_count,
            "checkpoint_dir": self.checkpoint_dir,
            "resumed_from_timesteps": self.resumed_from_timesteps,
            "created_at": self.created_at,
        }

    def document(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "TrainingRun":
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in document.items() if k in names})


def read_progress(checkpoint_dir: str | None) -> dict[str, Any] | None:
    """Actual progress written by train_rl.py (timesteps + latest checkpoint)."""
    if not checkpoint_dir:
        return None
    path = Path(checkpoint_dir) / "progress.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data.get("timesteps"), int) else None


def latest_checkpoint(checkpoint_dir: str | None) -> tuple[Path, int] | None:
    """The latest complete resume point and the timesteps it contains."""
    if not checkpoint_dir:
        return None
    path = Path(checkpoint_dir) / "latest.zip"
    try:
        timesteps = json.loads((Path(checkpoint_dir) / "checkpoint.json").read_text())["timesteps"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(timesteps, int) or not path.is_file() or not zipfile.is_zipfile(path):
        return None
    return path, timesteps


class TrainingManager:
    """Owns at most one leased run per process; recovers abandoned durable runs."""

    def __init__(self, store: Any | None = None) -> None:
        self.runs: list[TrainingRun] = []
        self.active_run: TrainingRun | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._monitor_task: asyncio.Task[None] | None = None
        self._store = store
        self._token: str | None = None
        self._release_on_cancel = False

    @property
    def store(self) -> Any:
        if self._store is None:
            from services import training_store
            self._store = training_store
        return self._store

    async def get_status(self) -> dict[str, Any]:
        """Return current training status summary from the durable run records."""
        models = self._list_models()
        try:
            history = [TrainingRun.from_document(d).to_dict() for d in reversed(await self.store.list_recent(20))]
        except Exception:
            logger.warning("Durable training history unavailable", exc_info=True)
            history = [r.to_dict() for r in self.runs[-20:]]
        return {
            "active_run": self.active_run.to_dict() if self.active_run else None,
            "history": history,
            "available_models": models,
            "available_training_types": ["rl"],
        }

    def get_config(self) -> dict[str, Any]:
        """Return training-related environment config and model status."""
        from services.rl.agent import is_loaded as rl_is_loaded, MODEL_PATH as rl_model_path

        rl_model_exists = Path(rl_model_path).exists()
        root = artifacts_dir()
        model_files: list[str] = []
        if root.exists():
            for p in sorted(root.rglob("*")):
                if p.is_file() and p.suffix in (".zip", ".lgbm", ".pkl"):
                    model_files.append(str(p.relative_to(root)))

        return {
            "rl_model_path": rl_model_path,
            "rl_model_exists": rl_model_exists,
            "rl_model_loaded": rl_is_loaded(),
            "models_dir": str(root),
            "models_dir_exists": root.exists(),
            "model_files": model_files,
            "env": {
                "RL_MODEL_PATH": os.getenv("RL_MODEL_PATH", "(not set)"),
                "RL_TIMESTEPS": os.getenv("RL_TIMESTEPS", "(not set)"),
                "RL_OUTPUT": os.getenv("RL_OUTPUT", "(not set)"),
                "TRAINING_ARTIFACTS_DIR": os.getenv("TRAINING_ARTIFACTS_DIR", "(not set)"),
                "LLM_BASE_URL": os.getenv("LLM_BASE_URL", "(not set)"),
                "LLM_MODEL": os.getenv("LLM_MODEL", "(not set)"),
                "LLM_API_KEY": "***" if os.getenv("LLM_API_KEY") else "(not set)",
            },
        }

    def _list_models(self) -> list[dict[str, Any]]:
        """List trained model archives (excluding resumable checkpoints)."""
        models: list[dict[str, Any]] = []
        root = artifacts_dir()
        if not root.exists():
            return models
        for p in sorted(root.rglob("*.zip")):
            if "checkpoints" in p.relative_to(root).parts or p.name.endswith(".partial.zip"):
                continue
            stat = p.stat()
            models.append({
                "path": str(p.relative_to(root)),
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return models

    async def start_training(self, model_type: str = "rl", timesteps: int = 50000) -> TrainingRun:
        """Persist a new run, take its lease and launch it."""
        if self.active_run and self.active_run.status == "running":
            raise ValueError("A training run is already in progress")
        if model_type != "rl":
            raise ValueError(f"Training {model_type!r} is unavailable; only RL training is implemented")
        if type(timesteps) is not int or not 1 <= timesteps <= 10_000_000:
            raise ValueError("timesteps must be an integer between 1 and 10000000")
        run_id = f"train-{model_type}-{uuid4().hex[:12]}"
        root = artifacts_dir()
        run = TrainingRun(
            id=run_id, model_type=model_type, status="queued", total_timesteps=timesteps,
            output_path=str(root / f"{run_id}.zip"),
            checkpoint_dir=str(root / "checkpoints" / run_id),
            seed=random.SystemRandom().randrange(1_000_000),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        await self.store.create(run.document())
        token = str(uuid4())
        claimed = await self.store.claim(token, lease_seconds(), run_id=run_id)
        if claimed is None:
            raise ValueError("Training run was claimed by another worker")
        return await self._launch(claimed, token)

    async def recover(self) -> TrainingRun | None:
        """Claim and resume a queued or abandoned durable run, if any."""
        if self.active_run is not None:
            return None
        token = str(uuid4())
        claimed = await self.store.claim(token, lease_seconds())
        if claimed is None:
            return None
        logger.info("Recovering training run %s (attempt %s)", claimed["id"], claimed.get("attempt_count"))
        return await self._launch(claimed, token)

    async def run(self, stop: asyncio.Event) -> None:
        """Background recovery loop: picks up runs released or abandoned by any worker."""
        while not stop.is_set():
            try:
                await self.recover()
            except Exception:
                logger.warning("Training recovery unavailable; durable runs retained", exc_info=True)
            try:
                await asyncio.wait_for(stop.wait(), timeout=recovery_poll_seconds())
            except asyncio.TimeoutError:
                pass

    def _command(self, run: TrainingRun, resume: Path | None) -> list[str]:
        script = str(Path(__file__).parent.parent / "training" / "train_rl.py")
        cmd = [
            sys.executable, "-u", script,
            "--timesteps", str(run.total_timesteps),
            "--output", str(run.output_path),
            "--seed", str(run.seed if run.seed is not None else 42),
            "--checkpoint-dir", str(run.checkpoint_dir),
            "--checkpoint-freq", str(checkpoint_every(run.total_timesteps)),
        ]
        if resume is not None:
            cmd += ["--resume", str(resume)]
        return cmd

    async def _launch(self, document: dict[str, Any], token: str) -> TrainingRun:
        run = TrainingRun.from_document(document)
        checkpoint = latest_checkpoint(run.checkpoint_dir)
        resume = checkpoint[0] if checkpoint else None
        run.resumed_from_timesteps = checkpoint[1] if checkpoint else 0
        run.current_timesteps = run.resumed_from_timesteps
        run.started_at = run.started_at or datetime.now(timezone.utc).isoformat()
        run.progress_pct = (run.current_timesteps / run.total_timesteps * 100) if run.total_timesteps else 0.0
        self.active_run, self._token = run, token
        self.runs = [r for r in self.runs if r.id != run.id] + [run]
        try:
            directory = Path(str(run.checkpoint_dir))
            directory.mkdir(parents=True, exist_ok=True)
            # Progress from an interrupted attempt may exceed its last checkpoint.
            staged = directory / "progress.json.pending"
            staged.write_text(json.dumps({"timesteps": run.resumed_from_timesteps,
                                          "checkpoint": str(resume) if resume else None,
                                          "completed": False}))
            staged.replace(directory / "progress.json")
            env = {**os.environ, "RL_TIMESTEPS": str(run.total_timesteps)}
            self._process = subprocess.Popen(
                self._command(run, resume), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
            )
            self._monitor_task = asyncio.create_task(self._monitor_process(run))
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc).isoformat()
            await self._finish(run)
            self.active_run, self._token = None, None
            logger.error("Failed to start training: %s", exc)
        return run

    async def _persist(self, run: TrainingRun) -> bool:
        """Fenced progress write + lease renewal; True when still the owner (or unleased)."""
        if self._token is None:
            return True
        return bool(await self.store.save(run.document(), self._token, lease_seconds()))

    async def _finish(self, run: TrainingRun) -> bool:
        if self._token is None:
            return True
        return bool(await self.store.finish(run.document(), self._token))

    async def _owns(self, run: TrainingRun) -> bool:
        if self._token is None:
            return True
        return bool(await self.store.renew(run.id, self._token, lease_seconds()))

    def _update_progress(self, run: TrainingRun) -> None:
        progress = read_progress(run.checkpoint_dir)
        if progress is not None:
            run.current_timesteps = min(progress["timesteps"], max(0, run.total_timesteps - 1))
            run.progress_estimated = False
        elif run.started_at:
            # No progress file yet: rough time-based estimate, labelled as such.
            elapsed = time.time() - datetime.fromisoformat(run.started_at).timestamp()
            run.current_timesteps = min(run.resumed_from_timesteps + int(elapsed * 1000),
                                        max(0, run.total_timesteps - 1))
            run.progress_estimated = True
        if run.total_timesteps:
            run.progress_pct = (run.current_timesteps / run.total_timesteps) * 100

    @staticmethod
    def _terminate(proc: subprocess.Popen[bytes] | None) -> None:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    async def _monitor_process(self, run: TrainingRun) -> None:
        """Monitor the training subprocess, persist progress and finalize under the lease."""
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
        heartbeat = max(0.5, min(2.0, lease_seconds() / 3))
        try:
            while proc.poll() is None:
                self._update_progress(run)
                if not await self._persist(run):
                    # Another worker owns this run now: stop without publishing.
                    logger.warning("Training run %s lease lost; terminating local attempt", run.id)
                    await asyncio.to_thread(self._terminate, proc)
                    run.status = "superseded"
                    return
                await asyncio.sleep(heartbeat)

            output = await output_task
            valid = (proc.returncode == 0 and run.output_path
                     and Path(run.output_path).is_file() and zipfile.is_zipfile(run.output_path))
            if valid and not await self._owns(run):
                logger.warning("Training run %s finished after losing its lease; not promoting", run.id)
                run.status = "superseded"
                return
            if valid:
                # Preserve the previous usable model until a successful job has
                # produced a new archive. Atomic replacement also survives restart.
                canonical = Path(os.getenv("RL_MODEL_PATH", str(artifacts_dir() / "rl_policy.zip")))
                canonical.parent.mkdir(parents=True, exist_ok=True)
                staged = canonical.with_suffix(".pending")
                shutil.copyfile(str(run.output_path), staged)
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
            run.completed_at = datetime.now(timezone.utc).isoformat()
            if not await self._finish(run):
                logger.warning("Training run %s completion was fenced by a newer owner", run.id)
        except asyncio.CancelledError:
            if self._release_on_cancel:
                logger.info("Training run %s released for recovery", run.id)
            else:
                run.status = "stopped"
                run.completed_at = datetime.now(timezone.utc).isoformat()
                logger.info("Training run %s stopped", run.id)
            raise
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.completed_at = datetime.now(timezone.utc).isoformat()
            logger.exception("Training finalization failed")
            try:
                await self._finish(run)
            except Exception:
                logger.warning("Training failure could not be persisted", exc_info=True)
        finally:
            self.active_run = None
            self._process = None
            if not output_task.done():
                output_task.cancel()

    async def _cancel_monitor(self) -> None:
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

    async def stop_training(self) -> bool:
        """Operator stop: terminate and reap the job, then record it as stopped (terminal)."""
        proc, run, token = self._process, self.active_run, self._token
        if proc is None or proc.poll() is not None:
            return False
        # Cancel the monitor first so it cannot finalize the terminated process as failed.
        self._release_on_cancel = False
        await self._cancel_monitor()
        await asyncio.to_thread(self._terminate, proc)
        self.active_run, self._process = None, None
        if run is not None and token is not None:
            run.status = "stopped"
            run.completed_at = run.completed_at or datetime.now(timezone.utc).isoformat()
            await self.store.finish(run.document(), token)
        self._token = None
        return True

    async def shutdown(self) -> None:
        """Graceful shutdown: stop the subprocess but keep the run resumable."""
        proc, run, token = self._process, self.active_run, self._token
        if proc is None:
            return
        self._release_on_cancel = True
        try:
            await self._cancel_monitor()
        finally:
            self._release_on_cancel = False
        await asyncio.to_thread(self._terminate, proc)
        self.active_run, self._process = None, None
        if run is not None and token is not None:
            try:
                await self.store.release(run.document(), token)
            except Exception:
                logger.warning("Training release failed; lease expiry will recover the run", exc_info=True)
        self._token = None


# Singleton instance
manager = TrainingManager()

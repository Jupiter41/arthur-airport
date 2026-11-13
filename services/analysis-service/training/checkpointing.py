"""Atomic, resumable PPO checkpoints and actual progress reporting (G7).

``latest.zip`` is the most recent complete checkpoint; ``progress.json`` holds
the real ``num_timesteps`` the trainer has reached. Both are replaced with
``os.replace`` so an abrupt exit never leaves a truncated resume point.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".json", delete=False) as handle:
        json.dump(payload, handle)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_progress(directory: Path, timesteps: int, *, checkpoint: str | None = None,
                   completed: bool = False) -> None:
    _write_json(directory / "progress.json",
                {"timesteps": int(timesteps), "checkpoint": checkpoint, "completed": completed})


def save_checkpoint(model, directory: Path) -> Path:
    """Save ``model`` as ``latest.zip`` atomically and record its timesteps."""
    directory.mkdir(parents=True, exist_ok=True)
    staged = directory / "latest.partial.zip"
    model.save(str(staged))
    target = directory / "latest.zip"
    os.replace(staged, target)
    # The resume point is the checkpoint's own timesteps, not the latest progress.
    _write_json(directory / "checkpoint.json", {"timesteps": int(model.num_timesteps)})
    write_progress(directory, int(model.num_timesteps), checkpoint=str(target))
    return target


def make_checkpoint_callback(directory: Path, frequency: int, progress_every: int = 256):
    from stable_baselines3.common.callbacks import BaseCallback

    class ResumableCheckpoint(BaseCallback):
        def __init__(self) -> None:
            super().__init__()
            self._next_checkpoint = 0
            self._next_progress = 0

        def _on_training_start(self) -> None:
            now = int(self.model.num_timesteps)
            self._next_checkpoint = now + frequency
            self._next_progress = now

        def _on_step(self) -> bool:
            now = int(self.model.num_timesteps)
            if now >= self._next_checkpoint:
                save_checkpoint(self.model, directory)
                self._next_checkpoint = now + frequency
                self._next_progress = now + progress_every
            elif now >= self._next_progress:
                write_progress(directory, now, checkpoint=str(directory / "latest.zip")
                               if (directory / "latest.zip").is_file() else None)
                self._next_progress = now + progress_every
            return True

    return ResumableCheckpoint()

"""Verify the environment version embedded in atomic SB3 policy archives."""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZipFile

from _common.effects import EFFECT_MODEL_VERSION


def require_compatible(path: str | Path) -> None:
    with ZipFile(path) as archive:
        data = json.loads(archive.read("data"))
    version = data.get("effect_model_version", "legacy")
    if version != EFFECT_MODEL_VERSION:
        raise ValueError(f"Policy effect model {version!r} is incompatible with {EFFECT_MODEL_VERSION!r}; retrain")
